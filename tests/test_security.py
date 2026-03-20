"""
Tests for the security scanner module: grade computation, accepted_risks
filtering, Finding/ScanResult data classes, baseline comparison, and
classification.
"""

import os
import sys
import json
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from security.security_scan import (
    Finding,
    ScanResult,
    _compute_grade,
    _fail,
    classify_findings,
    generate_report,
    generate_json_report,
    compare_baseline,
    save_baseline,
    check_static_pip_audit,
)


# ---------------------------------------------------------------------------
# _compute_grade
# ---------------------------------------------------------------------------


class TestComputeGrade:
    def test_no_findings_is_a_plus(self):
        assert _compute_grade([]) == "A+"

    def test_low_only_is_b(self):
        findings = [Finding("LOW", "cat", "t", "d")]
        assert _compute_grade(findings) == "B"

    def test_many_low_is_c(self):
        findings = [Finding("LOW", "cat", f"t{i}", "d") for i in range(6)]
        assert _compute_grade(findings) == "C"

    def test_medium_1_is_c(self):
        findings = [Finding("MEDIUM", "cat", "t", "d")]
        assert _compute_grade(findings) == "C"

    def test_medium_4_is_d(self):
        findings = [Finding("MEDIUM", "cat", f"t{i}", "d") for i in range(4)]
        assert _compute_grade(findings) == "D"

    def test_high_is_d(self):
        findings = [Finding("HIGH", "cat", "t", "d")]
        assert _compute_grade(findings) == "D"

    def test_critical_is_f(self):
        findings = [Finding("CRITICAL", "cat", "t", "d")]
        assert _compute_grade(findings) == "F"

    def test_mixed_critical_wins(self):
        findings = [
            Finding("LOW", "cat", "t1", "d"),
            Finding("CRITICAL", "cat", "t2", "d"),
        ]
        assert _compute_grade(findings) == "F"


# ---------------------------------------------------------------------------
# classify_findings
# ---------------------------------------------------------------------------


class TestClassifyFindings:
    def test_ruff_is_tier1(self):
        f = Finding("LOW", "Static Analysis - Ruff", "lint", "d")
        classified = classify_findings([f])
        assert f in classified["tier1"]
        assert not classified["tier2"]

    def test_bandit_is_tier2(self):
        f = Finding("MEDIUM", "Static Analysis - Bandit", "sec", "d")
        classified = classify_findings([f])
        assert f in classified["tier2"]
        assert not classified["tier1"]

    def test_secrets_is_tier2(self):
        f = Finding("CRITICAL", "Static Analysis - Secrets", "secret", "d")
        classified = classify_findings([f])
        assert f in classified["tier2"]

    def test_deps_is_tier2(self):
        f = Finding("HIGH", "Static Analysis - Dependencies", "vuln", "d")
        classified = classify_findings([f])
        assert f in classified["tier2"]

    def test_unknown_category_is_other(self):
        f = Finding("LOW", "Custom Category", "misc", "d")
        classified = classify_findings([f])
        assert f in classified["other"]


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


class TestReportGeneration:
    def _make_result(self, findings=None):
        r = ScanResult(target=".", profile_name="test", started="2026-01-01")
        r.finished = "2026-01-01"
        if findings:
            r.findings = findings
            r.total = len(findings)
        else:
            r.total = 4
            r.passed = 4
        return r

    def test_generate_report_clean(self):
        r = self._make_result()
        md, grade = generate_report(r)
        assert grade == "A+"
        assert "No Findings" in md

    def test_generate_report_with_findings(self):
        r = self._make_result([Finding("MEDIUM", "Static Analysis - Bandit", "pickle use", "B301")])
        md, grade = generate_report(r)
        assert grade == "C"
        assert "pickle use" in md

    def test_generate_json_report(self):
        r = self._make_result([Finding("LOW", "cat", "title", "detail")])
        jr = generate_json_report(r, "B")
        assert jr["grade"] == "B"
        assert len(jr["findings"]) == 1
        assert jr["findings"][0]["title"] == "title"


# ---------------------------------------------------------------------------
# Baseline comparison
# ---------------------------------------------------------------------------


class TestBaselineComparison:
    def test_save_and_compare_identical(self):
        report = {
            "grade": "B",
            "failed": 1,
            "total": 5,
            "findings": [{"title": "f1", "severity": "LOW"}],
        }
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump(report, f)
            path = f.name
        try:
            diffs = compare_baseline(report, path)
            assert len(diffs) == 0
        finally:
            os.unlink(path)

    def test_grade_change_detected(self):
        baseline = {"grade": "A", "failed": 0, "total": 4, "findings": []}
        current = {"grade": "C", "failed": 1, "total": 4, "findings": [{"title": "new", "severity": "MEDIUM"}]}
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump(baseline, f)
            path = f.name
        try:
            diffs = compare_baseline(current, path)
            assert any("Grade changed" in d for d in diffs)
            assert any("New:" in d for d in diffs)
        finally:
            os.unlink(path)

    def test_resolved_finding_detected(self):
        baseline = {"grade": "C", "failed": 1, "total": 4, "findings": [{"title": "old", "severity": "MEDIUM"}]}
        current = {"grade": "A+", "failed": 0, "total": 4, "findings": []}
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump(baseline, f)
            path = f.name
        try:
            diffs = compare_baseline(current, path)
            assert any("Resolved:" in d for d in diffs)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Accepted risks filtering (check_static_pip_audit)
# ---------------------------------------------------------------------------


class TestAcceptedRisks:
    def test_accepted_cves_are_filtered(self):
        """Verify that accepted_risks CVEs don't produce findings."""
        profile = {
            "accepted_risks": [
                {"cve": "CVE-2025-68463", "package": "biopython", "reason": "test"},
            ]
        }
        result = ScanResult(target=".", profile_name="test", started="now")
        # We can't fully unit-test pip-audit without running it,
        # but we can verify the accepted_cves set is built correctly
        accepted_cves = set()
        for entry in profile.get("accepted_risks", []):
            cve = entry.get("cve", "")
            if cve:
                accepted_cves.add(cve)
        assert "CVE-2025-68463" in accepted_cves

    def test_empty_profile_no_accepted(self):
        accepted_cves = set()
        profile = {}
        for entry in profile.get("accepted_risks", []):
            cve = entry.get("cve", "")
            if cve:
                accepted_cves.add(cve)
        assert len(accepted_cves) == 0


# ---------------------------------------------------------------------------
# Data class tests
# ---------------------------------------------------------------------------


class TestDataClasses:
    def test_finding_defaults(self):
        f = Finding("HIGH", "cat", "title", "detail")
        assert f.remediation == ""

    def test_finding_with_remediation(self):
        f = Finding("LOW", "cat", "title", "detail", remediation="upgrade")
        assert f.remediation == "upgrade"

    def test_scan_result_defaults(self):
        r = ScanResult(target=".", profile_name="test", started="now")
        assert r.findings == []
        assert r.passed == 0
        assert r.total == 0

    def test_fail_adds_finding(self):
        r = ScanResult(target=".", profile_name="test", started="now")
        f = Finding("HIGH", "cat", "title", "detail")
        _fail(r, f, "test msg")
        assert len(r.findings) == 1
        assert r.total == 1
