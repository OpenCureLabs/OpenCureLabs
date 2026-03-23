"""Tests for the log analyzer (scripts/log_analyzer.py).

Covers log line parsing (both formats), pattern matching for every error
category, fixture-based integration scanning, and optional real-log scanning.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Ensure the scripts directory is importable
PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

from log_analyzer import (  # noqa: E402
    Finding,
    ScanSummary,
    find_latest_genesis,
    find_log_files,
    format_json,
    format_text,
    main,
    parse_line,
    scan,
    scan_file,
)

FIXTURES_DIR = PROJECT_DIR / "tests" / "fixtures" / "logs"
LOGS_DIR = PROJECT_DIR / "logs"


# ══════════════════════════════════════════════════════════════════════════════
# Group 1 — Line Parser
# ══════════════════════════════════════════════════════════════════════════════


class TestParseLineGenesis:
    """Parse genesis/runall log format."""

    def test_info_line(self):
        line = "2026-03-23 13:36:55 - INFO     - nat.cli.commands.start:192 - Starting NAT from config file: 'coordinator/labclaw_workflow.yaml'"
        result = parse_line(line)
        assert result is not None
        ts, level, module, msg = result
        assert ts == "2026-03-23 13:36:55"
        assert level == "INFO"
        assert module == "nat.cli.commands.start:192"
        assert "Starting NAT" in msg

    def test_warning_line(self):
        line = "2026-03-23 13:35:29 - WARNING  - labclaw.skills.structure:128 - ESMFold HTTP error: 413 Client Error"
        result = parse_line(line)
        assert result is not None
        assert result[1] == "WARNING"
        assert "ESMFold" in result[3]

    def test_error_line(self):
        line = "2026-03-23 13:35:30 - ERROR    - nat.builder.function:202 - Error with ainvoke in function"
        result = parse_line(line)
        assert result is not None
        assert result[1] == "ERROR"
        assert "ainvoke" in result[3]

    def test_httpx_line(self):
        line = '2026-03-23 10:00:02 - INFO     - httpx:1740 - HTTP Request: POST https://generativelanguage.googleapis.com/v1beta/openai/chat/completions "HTTP/1.1 200 OK"'
        result = parse_line(line)
        assert result is not None
        assert "generativelanguage" in result[3]


class TestParseLineBatch:
    """Parse batch log format (comma-separated milliseconds)."""

    def test_info_line(self):
        line = "2026-03-22 01:26:20,849 labclaw.compute.batch_dispatcher INFO: === CONTINUOUS MODE ==="
        result = parse_line(line)
        assert result is not None
        ts, level, module, msg = result
        assert ts == "2026-03-22 01:26:20,849"
        assert level == "INFO"
        assert module == "labclaw.compute.batch_dispatcher"
        assert "CONTINUOUS MODE" in msg

    def test_error_line(self):
        line = "2026-03-22 01:26:36,874 labclaw.compute.pool_manager ERROR: Failed to provision from offer 33299522: 400 Client Error"
        result = parse_line(line)
        assert result is not None
        assert result[1] == "ERROR"
        assert "provision" in result[3]


class TestParseLineUnstructured:
    """Non-log lines should return None."""

    def test_config_summary(self):
        assert parse_line("Configuration Summary:") is None

    def test_progress_bar(self):
        assert parse_line("1/1 [==============================] - 0s 28ms/step") is None

    def test_vcf_warning(self):
        assert parse_line("[W::vcf_parse] Contig '17' is not defined in the header.") is None

    def test_bare_error(self):
        assert parse_line("Error: Cannot exit the context without completing the workflow") is None

    def test_empty_line(self):
        assert parse_line("") is None

    def test_ansi_codes(self):
        assert parse_line("\x1b[32mWorkflow Result:\n\x1b[39m") is None


# ══════════════════════════════════════════════════════════════════════════════
# Group 2 — Pattern Matching
# ══════════════════════════════════════════════════════════════════════════════


class TestPatternAlphaFold:
    """AlphaFold API error detection."""

    def test_500_error(self):
        line = "Error with ainvoke in function with input: {}. Error: 500 Server Error: Internal Server Error for url: https://alphafold.ebi.ac.uk/api/prediction/P04637"
        _assert_category(line, "alphafold_api", "CRITICAL")

    def test_workflow_error(self):
        line = "Error running workflow: 500 Server Error: Internal Server Error for url: https://alphafold.ebi.ac.uk/api/prediction/P12830"
        # This matches nat_coordinator first (Error running workflow)
        _assert_any_category(line, {"nat_coordinator", "alphafold_api"})


class TestPatternESMFold:
    """ESMFold API error detection."""

    def test_413_error(self):
        line = "ESMFold HTTP error: 413 Client Error: Request Entity Too Large for url: https://api.esmatlas.com/foldSequence/v1/pdb/"
        _assert_category(line, "esmfold_api", "HIGH")


class TestPatternGemini:
    """Gemini API error detection."""

    def test_http_error(self):
        line = 'HTTP Request: POST https://generativelanguage.googleapis.com/v1beta/openai/chat/completions "HTTP/1.1 429 Too Many Requests"'
        _assert_category(line, "gemini_api", "CRITICAL")

    def test_200_not_flagged(self):
        line = 'HTTP Request: POST https://generativelanguage.googleapis.com/v1beta/openai/chat/completions "HTTP/1.1 200 OK"'
        _assert_no_match(line, exclude_low=True)

    def test_recitation(self):
        _assert_category("finish_reason: RECITATION", "gemini_api", "CRITICAL")


class TestPatternGrok:
    """Grok / xAI API error detection."""

    def test_json_parse_failure(self):
        line = "Failed to parse Grok critique JSON: Invalid control character at: line 17 column 61 (char 1642)"
        _assert_category(line, "grok_api", "HIGH")

    def test_score_none(self):
        line = "Grok critique: overall_score=None, recommendation=revise"
        # The score=None pattern should match — but the pattern uses `Grok\s+critique:.*score=None`
        # and the actual log says `overall_score=None` which contains `score=None`
        _assert_category(line, "grok_api", "HIGH")

    def test_200_not_flagged(self):
        line = 'HTTP Request: POST https://api.x.ai/v1/chat/completions "HTTP/1.1 200 OK"'
        _assert_no_match(line, exclude_low=True)

    def test_xai_http_error(self):
        line = 'HTTP Request: POST https://api.x.ai/v1/chat/completions "HTTP/1.1 500 Internal Server Error"'
        _assert_category(line, "grok_api", "HIGH")


class TestPatternVastai:
    """Vast.ai infrastructure error detection."""

    def test_provision_failure(self):
        line = "Failed to provision from offer 33299522: 400 Client Error: Bad Request"
        _assert_category(line, "vastai", "HIGH")

    def test_dispatch_failure(self):
        line = "Vast.ai dispatch failed: 400 Client Error: Bad Request for url: https://console.vast.ai/api/v0/asks/12345/"
        _assert_category(line, "vastai", "HIGH")

    def test_remote_execution_failure(self):
        line = "Remote execution failed (exit 1): VCF not found"
        _assert_category(line, "vastai", "HIGH")

    def test_job_final_failure(self):
        line = "Job 2364 failed (retry 3): Remote execution failed (exit 1)"
        _assert_category(line, "vastai", "HIGH")


class TestPatternNAT:
    """NAT / Coordinator error detection."""

    def test_workflow_init_failure(self):
        _assert_category("Failed to initialize workflow", "nat_coordinator", "CRITICAL")

    def test_workflow_error(self):
        _assert_category("Error running workflow: something broke", "nat_coordinator", "CRITICAL")

    def test_ainvoke_error(self):
        _assert_category("Error with ainvoke in function with input: {}", "nat_coordinator", "CRITICAL")

    def test_context_error(self):
        _assert_category("Cannot exit the context without completing the workflow", "nat_coordinator", "CRITICAL")


class TestPatternSafety:
    """Safety block detection."""

    def test_blocked(self):
        line = "Safety check BLOCKED: Confidence score 0.0089 below minimum threshold 0.1"
        _assert_category(line, "safety_block", "MEDIUM")

    def test_passed_not_flagged(self):
        _assert_no_match("Safety check PASSED", exclude_low=True)


class TestPatternAgentFailure:
    """Agent run failure detection."""

    def test_failed_status(self):
        line = "Completed agent run 101 with status: failed"
        _assert_category(line, "agent_failure", "HIGH")

    def test_completed_status_not_flagged(self):
        _assert_no_match("Completed agent run 200 with status: completed", exclude_low=True)


class TestPatternTraceback:
    """Python traceback detection."""

    def test_traceback_detected(self):
        _assert_category("Traceback (most recent call last):", "traceback", "HIGH")


class TestPatternNoise:
    """Dependency noise detection (LOW severity)."""

    def test_future_warning(self):
        _assert_category("FutureWarning: Downcasting behavior", "dependency_noise", "LOW", include_noise=True)

    def test_vcf_parse(self):
        _assert_category("[W::vcf_parse] Contig '17' is not defined", "dependency_noise", "LOW", include_noise=True)

    def test_cuda_error(self):
        _assert_category("Failed call to cudaGetRuntimeVersion", "dependency_noise", "LOW", include_noise=True)

    def test_noise_hidden_by_default(self):
        """LOW-severity noise should not appear with default settings."""
        _assert_no_match("FutureWarning: Downcasting behavior", exclude_low=True)


# ══════════════════════════════════════════════════════════════════════════════
# Group 3 — Log Discovery
# ══════════════════════════════════════════════════════════════════════════════


class TestLogDiscovery:
    """find_log_files and find_latest_genesis."""

    def test_find_files_in_directory(self):
        files = find_log_files(FIXTURES_DIR / "genesis-fixture")
        assert len(files) == 3
        names = {f.name for f in files}
        assert "task-1-Test_Structure.log" in names
        assert "task-2-Test_Variants.log" in names

    def test_find_single_file(self):
        f = FIXTURES_DIR / "batch-fixture.log"
        files = find_log_files(f)
        assert len(files) == 1
        assert files[0].name == "batch-fixture.log"

    def test_find_nonexistent(self):
        files = find_log_files(Path("/nonexistent/path"))
        assert files == []

    def test_latest_genesis_fixture(self):
        # The fixtures dir has genesis-fixture which alphabetically is latest
        result = find_latest_genesis(FIXTURES_DIR)
        assert result is not None
        assert "genesis-fixture" in result.name


# ══════════════════════════════════════════════════════════════════════════════
# Group 4 — File Scanning (Fixture Integration)
# ══════════════════════════════════════════════════════════════════════════════


class TestScanFixtureGenesis:
    """Scan the genesis-fixture directory and verify expected findings."""

    def test_scan_genesis_fixture(self):
        summary = scan([FIXTURES_DIR / "genesis-fixture"])

        assert summary.files_scanned == 3
        assert summary.total_lines > 0

        cats = summary.by_category

        # task-1 has: ESMFold (HIGH), AlphaFold (CRITICAL), NAT errors (CRITICAL),
        #   agent failures (HIGH), context error (CRITICAL)
        assert cats.get("esmfold_api", 0) >= 1
        assert cats.get("alphafold_api", 0) >= 1 or cats.get("nat_coordinator", 0) >= 1
        assert cats.get("agent_failure", 0) >= 1

        # task-3 has: Vast.ai dispatch (HIGH), Grok JSON parse (HIGH),
        #   safety block (MEDIUM)
        assert cats.get("vastai", 0) >= 1
        assert cats.get("grok_api", 0) >= 1
        assert cats.get("safety_block", 0) >= 1

    def test_clean_file_has_no_findings(self):
        """task-2 (Test_Variants) is a clean run — no errors."""
        line_count, findings = scan_file(
            FIXTURES_DIR / "genesis-fixture" / "task-2-Test_Variants.log"
        )
        assert line_count > 0
        assert len(findings) == 0

    def test_noisy_file_findings(self):
        """task-3 has dependency noise — only found when include_noise=True."""
        _, findings_no_noise = scan_file(
            FIXTURES_DIR / "genesis-fixture" / "task-3-Test_Neoantigen.log",
            include_noise=False,
        )
        _, findings_with_noise = scan_file(
            FIXTURES_DIR / "genesis-fixture" / "task-3-Test_Neoantigen.log",
            include_noise=True,
        )
        noise_findings = [f for f in findings_with_noise if f.severity == "LOW"]
        assert len(findings_with_noise) > len(findings_no_noise)
        assert any(f.category == "dependency_noise" for f in noise_findings)


class TestScanFixtureBatch:
    """Scan the batch-fixture.log and verify expected findings."""

    def test_scan_batch_fixture(self):
        summary = scan([FIXTURES_DIR / "batch-fixture.log"])

        assert summary.files_scanned == 1
        cats = summary.by_category

        # Batch has: 2x provision failures (Vast.ai), remote exec failure,
        #   job final failure, traceback
        assert cats.get("vastai", 0) >= 2
        assert cats.get("traceback", 0) >= 1

    def test_traceback_collapsed(self):
        """Multi-line traceback should produce a single finding, not one per line."""
        _, findings = scan_file(FIXTURES_DIR / "batch-fixture.log")
        traceback_findings = [f for f in findings if f.category == "traceback"]
        assert len(traceback_findings) == 1
        assert "RemoteExecutionError" in traceback_findings[0].message


# ══════════════════════════════════════════════════════════════════════════════
# Group 5 — Severity Filtering
# ══════════════════════════════════════════════════════════════════════════════


class TestSeverityFiltering:
    """Verify min_severity filtering works."""

    def test_critical_only(self):
        summary = scan(
            [FIXTURES_DIR / "genesis-fixture"],
            min_severity="CRITICAL",
        )
        for f in summary.findings:
            assert f.severity == "CRITICAL"

    def test_medium_includes_high(self):
        summary = scan(
            [FIXTURES_DIR / "genesis-fixture"],
            min_severity="MEDIUM",
        )
        severities = {f.severity for f in summary.findings}
        # Should include CRITICAL, HIGH, and MEDIUM — not LOW
        assert "LOW" not in severities

    def test_low_includes_everything(self):
        summary = scan(
            [FIXTURES_DIR / "genesis-fixture"],
            include_noise=True,
            min_severity="LOW",
        )
        severities = {f.severity for f in summary.findings}
        assert "LOW" in severities


# ══════════════════════════════════════════════════════════════════════════════
# Group 6 — Output Formatting
# ══════════════════════════════════════════════════════════════════════════════


class TestFormatText:
    """Human-readable text output."""

    def test_contains_header(self):
        summary = scan([FIXTURES_DIR / "genesis-fixture"])
        text = format_text(summary)
        assert "Log Analysis Report" in text
        assert "Files scanned" in text

    def test_contains_severity_counts(self):
        summary = scan([FIXTURES_DIR / "genesis-fixture"])
        text = format_text(summary)
        assert "By Severity" in text
        assert "CRITICAL" in text

    def test_contains_findings(self):
        summary = scan([FIXTURES_DIR / "genesis-fixture"])
        text = format_text(summary)
        assert "Findings" in text


class TestFormatJSON:
    """JSON output."""

    def test_valid_json(self):
        summary = scan([FIXTURES_DIR / "genesis-fixture"])
        output = format_json(summary)
        data = json.loads(output)
        assert "files_scanned" in data
        assert "findings" in data
        assert isinstance(data["findings"], list)

    def test_json_structure(self):
        summary = scan([FIXTURES_DIR / "genesis-fixture"])
        data = json.loads(format_json(summary))
        assert data["files_scanned"] == 3
        for finding in data["findings"]:
            assert "category" in finding
            assert "severity" in finding
            assert "file" in finding
            assert "line_number" in finding
            assert "message" in finding


# ══════════════════════════════════════════════════════════════════════════════
# Group 7 — CLI Entrypoint
# ══════════════════════════════════════════════════════════════════════════════


class TestCLI:
    """main() function with argv simulation."""

    def test_scan_fixture_dir(self):
        rc = main([str(FIXTURES_DIR / "genesis-fixture")])
        # Has CRITICAL findings → exit code 2
        assert rc == 2

    def test_scan_clean_file(self):
        rc = main([str(FIXTURES_DIR / "genesis-fixture" / "task-2-Test_Variants.log")])
        assert rc == 0

    def test_json_output(self, capsys):
        main([str(FIXTURES_DIR / "genesis-fixture"), "--json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["files_scanned"] == 3

    def test_severity_filter(self, capsys):
        main([str(FIXTURES_DIR / "genesis-fixture"), "--json", "--severity", "CRITICAL"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        for f in data["findings"]:
            assert f["severity"] == "CRITICAL"

    def test_nonexistent_path(self):
        rc = main(["/nonexistent/path/to/logs"])
        assert rc == 1

    def test_batch_file(self):
        rc = main([str(FIXTURES_DIR / "batch-fixture.log")])
        # Has HIGH findings (vastai, traceback) → exit code 1
        assert rc >= 1


# ══════════════════════════════════════════════════════════════════════════════
# Group 8 — Real Log Integration (optional)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestRealLogIntegration:
    """Scan real log files if available. Validates the scanner doesn't crash.

    Run with: pytest tests/test_log_analysis.py -m integration
    """

    @pytest.fixture(autouse=True)
    def _skip_if_no_logs(self):
        if not LOGS_DIR.is_dir():
            pytest.skip("No logs/ directory available")
        genesis = find_latest_genesis(LOGS_DIR)
        if genesis is None:
            pytest.skip("No genesis-* directories found")
        self.genesis_dir = genesis

    def test_scan_latest_genesis(self):
        """Scanner completes on real genesis logs without exceptions."""
        summary = scan([self.genesis_dir])
        assert summary.files_scanned > 0
        assert summary.total_lines > 0
        # Don't assert zero errors — real runs have known issues

    def test_scan_produces_structured_output(self):
        """Output is valid JSON."""
        summary = scan([self.genesis_dir])
        output = format_json(summary)
        data = json.loads(output)
        assert isinstance(data["findings"], list)
        assert data["files_scanned"] > 0

    def test_scan_with_noise(self):
        """Include LOW-severity noise — scanner should still complete."""
        summary = scan([self.genesis_dir], include_noise=True, min_severity="LOW")
        assert summary.files_scanned > 0

    def test_scan_runall_logs(self):
        """Scan individual runall logs if present."""
        runall_files = sorted(LOGS_DIR.glob("runall-*.log"))
        if not runall_files:
            pytest.skip("No runall logs found")
        # Scan just the last 5
        summary = scan(runall_files[-5:])
        assert summary.files_scanned > 0

    def test_scan_batch_logs(self):
        """Scan batch logs if present."""
        batch_files = sorted(LOGS_DIR.glob("batch-*.log"))
        if not batch_files:
            pytest.skip("No batch logs found")
        summary = scan(batch_files[-3:])
        assert summary.files_scanned > 0


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _scan_line(message: str, include_noise: bool = False) -> list[Finding]:
    """Helper: scan a single message line and return findings."""
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        # Wrap message in a valid genesis-format log line
        f.write(f"2026-01-01 00:00:00 - ERROR    - test:1 - {message}\n")
        f.flush()
        path = Path(f.name)

    try:
        _, findings = scan_file(path, include_noise=include_noise)
        return findings
    finally:
        path.unlink()


def _assert_category(
    message: str,
    expected_category: str,
    expected_severity: str,
    include_noise: bool = False,
):
    """Assert that a message matches the expected category and severity."""
    findings = _scan_line(message, include_noise=include_noise)
    assert len(findings) >= 1, f"No findings for: {message}"
    cats = [f.category for f in findings]
    assert expected_category in cats, (
        f"Expected category '{expected_category}' not found in {cats} for: {message}"
    )
    match = next(f for f in findings if f.category == expected_category)
    assert match.severity == expected_severity, (
        f"Expected severity '{expected_severity}', got '{match.severity}' for: {message}"
    )


def _assert_any_category(message: str, expected_categories: set[str]):
    """Assert that a message matches any of the expected categories."""
    findings = _scan_line(message)
    assert len(findings) >= 1, f"No findings for: {message}"
    cats = {f.category for f in findings}
    assert cats & expected_categories, (
        f"Expected one of {expected_categories}, got {cats} for: {message}"
    )


def _assert_no_match(message: str, exclude_low: bool = False):
    """Assert that a message does NOT match any patterns."""
    findings = _scan_line(message, include_noise=not exclude_low)
    if exclude_low:
        findings = [f for f in findings if f.severity != "LOW"]
    assert len(findings) == 0, (
        f"Unexpected findings for: {message} → {[(f.category, f.severity) for f in findings]}"
    )
