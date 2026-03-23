#!/usr/bin/env python3
"""Log analyzer for OpenCure Labs research pipeline output.

Parses genesis, runall, and batch log files to detect errors, warnings, and
API-specific issues (Gemini, Grok, AlphaFold, ESMFold, Vast.ai, NAT).

Usage:
    python scripts/log_analyzer.py                        # scan most recent genesis dir
    python scripts/log_analyzer.py --latest-genesis       # same, explicit
    python scripts/log_analyzer.py logs/runall-*.log      # scan specific files
    python scripts/log_analyzer.py logs/genesis-20260323-133653/  # scan a directory
    python scripts/log_analyzer.py --json                 # JSON output
    python scripts/log_analyzer.py --severity CRITICAL    # only critical findings
    python scripts/log_analyzer.py --include-noise        # include LOW-severity noise
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# ── Severity levels (ordered) ───────────────────────────────────────────────

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class ParsedLine:
    """A single parsed log line."""
    file: str
    line_number: int
    timestamp: str
    level: str
    module: str
    message: str
    raw: str


@dataclass
class Finding:
    """A categorized issue found in a log file."""
    category: str
    severity: str
    file: str
    line_number: int
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScanSummary:
    """Aggregated scan results."""
    files_scanned: int = 0
    total_lines: int = 0
    findings: list[Finding] = field(default_factory=list)

    @property
    def by_severity(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        return counts

    @property
    def by_category(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.category] = counts.get(f.category, 0) + 1
        return counts

    @property
    def by_file(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.file] = counts.get(f.file, 0) + 1
        return counts

    def to_dict(self) -> dict:
        return {
            "files_scanned": self.files_scanned,
            "total_lines": self.total_lines,
            "by_severity": self.by_severity,
            "by_category": self.by_category,
            "by_file": self.by_file,
            "findings": [f.to_dict() for f in self.findings],
        }


# ── Error patterns ───────────────────────────────────────────────────────────
#
# Each entry: (category, severity, compiled_regex)
# Patterns are matched against the full message text (case-insensitive).

_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    # AlphaFold API errors
    ("alphafold_api", "CRITICAL", re.compile(
        r"(?:500|502|503|504)\s+Server\s+Error.*alphafold\.ebi\.ac\.uk"
        r"|alphafold\.ebi\.ac\.uk.*(?:500|502|503|504)",
        re.IGNORECASE,
    )),

    # ESMFold API errors
    ("esmfold_api", "HIGH", re.compile(
        r"ESMFold\s+HTTP\s+error:\s+\d+"
        r"|esmatlas\.com.*(?:error|Error|timeout)",
        re.IGNORECASE,
    )),

    # Gemini API errors (HTTP errors on the googleapis endpoint)
    ("gemini_api", "CRITICAL", re.compile(
        r"generativelanguage\.googleapis\.com.*\"HTTP/[\d.]+\s+(?:4\d\d|5\d\d)"
        r"|RECITATION"
        r"|quota.*exceeded.*generativelanguage"
        r"|finish_reason.*(?:SAFETY|OTHER)"
        r"|generativelanguage\.googleapis\.com.*(?:error|Error|timeout|Timeout)",
        re.IGNORECASE,
    )),

    # Grok / xAI API errors
    ("grok_api", "HIGH", re.compile(
        r"Failed\s+to\s+parse\s+Grok\s+critique\s+JSON"
        r"|api\.x\.ai.*\"HTTP/[\d.]+\s+(?:4\d\d|5\d\d)"
        r"|api\.x\.ai.*(?:error|Error|timeout|Timeout)"
        r"|Grok\s+critique:.*score=None",
        re.IGNORECASE,
    )),

    # Vast.ai infrastructure errors
    ("vastai", "HIGH", re.compile(
        r"Failed\s+to\s+provision\s+from\s+offer"
        r"|Vast\.ai\s+dispatch\s+failed"
        r"|Remote\s+execution\s+failed"
        r"|SSH.*(?:timeout|timed\s+out)"
        r"|Job\s+\d+\s+failed\s+\(retry\s+\d+\)",
        re.IGNORECASE,
    )),

    # NAT / Coordinator errors
    ("nat_coordinator", "CRITICAL", re.compile(
        r"Failed\s+to\s+initialize\s+workflow"
        r"|Error\s+running\s+workflow"
        r"|Error\s+with\s+ainvoke\s+in\s+function"
        r"|Cannot\s+exit\s+the\s+context\s+without\s+completing",
        re.IGNORECASE,
    )),

    # Safety check blocks
    ("safety_block", "MEDIUM", re.compile(
        r"Safety\s+check\s+BLOCKED",
        re.IGNORECASE,
    )),

    # Agent run failures
    ("agent_failure", "HIGH", re.compile(
        r"Completed\s+agent\s+run\s+\d+\s+with\s+status:\s*failed",
        re.IGNORECASE,
    )),

    # Python tracebacks
    ("traceback", "HIGH", re.compile(
        r"Traceback\s+\(most\s+recent\s+call\s+last\)",
    )),

    # Dependency / infrastructure noise (LOW — hidden by default)
    ("dependency_noise", "LOW", re.compile(
        r"FutureWarning"
        r"|DeprecationWarning"
        r"|pkg_resources\s+is\s+deprecated"
        r"|\[W::vcf_parse\]"
        r"|Failed\s+call\s+to\s+cudaGetRuntimeVersion"
        r"|CUDNN_STATUS_INTERNAL_ERROR"
        r"|UserWarning.*mhcflurry",
        re.IGNORECASE,
    )),
]


# ── Log line parsers ─────────────────────────────────────────────────────────

# Genesis / Runall format:
#   2026-03-23 13:36:55 - INFO     - nat.cli.commands.start:192 - Starting NAT...
_RE_GENESIS = re.compile(
    r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})"  # timestamp
    r"\s+-\s+"
    r"(\w+)\s+"                                     # level (INFO, WARNING, ERROR)
    r"-\s+"
    r"([\w.:]+)"                                    # module:line
    r"\s+-\s+"
    r"(.*)$"                                        # message
)

# Batch format:
#   2026-03-22 01:26:20,849 labclaw.compute.batch_dispatcher INFO: message
_RE_BATCH = re.compile(
    r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d{3})"  # timestamp with millis
    r"\s+"
    r"([\w.]+)"                                           # module
    r"\s+"
    r"(\w+):\s+"                                          # level + colon
    r"(.*)$"                                              # message
)

# Unstructured error line (standalone "Error: ...")
_RE_BARE_ERROR = re.compile(r"^Error:\s+", re.IGNORECASE)


def parse_line(raw: str) -> tuple[str, str, str, str] | None:
    """Parse a log line into (timestamp, level, module, message) or None."""
    m = _RE_GENESIS.match(raw)
    if m:
        return m.group(1), m.group(2).strip(), m.group(3), m.group(4)

    m = _RE_BATCH.match(raw)
    if m:
        return m.group(1), m.group(3).strip(), m.group(2), m.group(4)

    return None


# ── Log discovery ────────────────────────────────────────────────────────────

def find_log_files(path: Path) -> list[Path]:
    """Find all .log files under a path (file or directory)."""
    if path.is_file() and path.suffix == ".log":
        return [path]
    if path.is_dir():
        return sorted(path.rglob("*.log"))
    return []


def find_latest_genesis(logs_dir: Path) -> Path | None:
    """Find the most recent genesis-* directory under logs_dir."""
    genesis_dirs = sorted(logs_dir.glob("genesis-*"), reverse=True)
    for d in genesis_dirs:
        if d.is_dir():
            return d
    return None


# ── Scanner ──────────────────────────────────────────────────────────────────

def scan_file(filepath: Path, include_noise: bool = False) -> tuple[int, list[Finding]]:
    """Scan a single log file and return (line_count, findings)."""
    findings: list[Finding] = []
    in_traceback = False
    traceback_start_line = 0
    traceback_file = ""

    try:
        lines = filepath.read_text(errors="replace").splitlines()
    except OSError:
        return 0, []

    file_str = str(filepath)

    for i, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped:
            continue

        # Track multi-line tracebacks — collapse into one finding
        if in_traceback:
            # Tracebacks end at the exception line (no leading whitespace, not
            # "File" or "Traceback" or whitespace-indented)
            if not stripped.startswith(("File ", "Traceback")) and not raw.startswith((" ", "\t")):
                in_traceback = False
                # The current line is the exception message — include it
                findings.append(Finding(
                    category="traceback",
                    severity="HIGH",
                    file=file_str,
                    line_number=traceback_start_line,
                    message=stripped,
                ))
            continue

        # Parse structured log line
        parsed = parse_line(stripped)
        message = parsed[3] if parsed else stripped

        # Match against patterns
        for category, severity, pattern in _PATTERNS:
            if not include_noise and severity == "LOW":
                continue

            if pattern.search(message) or (not parsed and pattern.search(stripped)):
                # Special handling: traceback start
                if category == "traceback":
                    in_traceback = True
                    traceback_start_line = i
                    traceback_file = file_str
                    break

                findings.append(Finding(
                    category=category,
                    severity=severity,
                    file=file_str,
                    line_number=i,
                    message=message[:300],
                ))
                break  # first match wins per line

    # If file ended mid-traceback
    if in_traceback:
        findings.append(Finding(
            category="traceback",
            severity="HIGH",
            file=traceback_file,
            line_number=traceback_start_line,
            message="(traceback at end of file)",
        ))

    return len(lines), findings


def scan(
    paths: list[Path],
    include_noise: bool = False,
    min_severity: str = "LOW",
) -> ScanSummary:
    """Scan multiple paths and return aggregated results."""
    summary = ScanSummary()
    all_files: list[Path] = []
    for p in paths:
        all_files.extend(find_log_files(p))

    severity_threshold = SEVERITY_ORDER.get(min_severity, 3)

    for filepath in all_files:
        line_count, findings = scan_file(filepath, include_noise=include_noise)
        summary.files_scanned += 1
        summary.total_lines += line_count
        for f in findings:
            if SEVERITY_ORDER.get(f.severity, 3) <= severity_threshold:
                summary.findings.append(f)

    return summary


# ── Reports ──────────────────────────────────────────────────────────────────

def format_text(summary: ScanSummary) -> str:
    """Format scan results as human-readable text."""
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("OpenCure Labs — Log Analysis Report")
    lines.append("=" * 70)
    lines.append(f"Files scanned : {summary.files_scanned}")
    lines.append(f"Total lines   : {summary.total_lines}")
    lines.append(f"Total findings: {len(summary.findings)}")
    lines.append("")

    # Severity summary
    by_sev = summary.by_severity
    if by_sev:
        lines.append("── By Severity ──")
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            if sev in by_sev:
                lines.append(f"  {sev:10s}: {by_sev[sev]}")
        lines.append("")

    # Category summary
    by_cat = summary.by_category
    if by_cat:
        lines.append("── By Category ──")
        for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
            lines.append(f"  {cat:25s}: {count}")
        lines.append("")

    # Per-file summary
    by_file = summary.by_file
    if by_file:
        lines.append("── By File ──")
        for fname, count in sorted(by_file.items(), key=lambda x: -x[1]):
            lines.append(f"  {count:4d}  {fname}")
        lines.append("")

    # Individual findings (grouped by severity)
    if summary.findings:
        lines.append("── Findings ──")
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            sev_findings = [f for f in summary.findings if f.severity == sev]
            if not sev_findings:
                continue
            lines.append(f"\n  [{sev}]")
            for f in sev_findings:
                short_file = Path(f.file).name
                msg = f.message[:200]
                lines.append(f"    {short_file}:{f.line_number} [{f.category}] {msg}")

    lines.append("")
    lines.append("=" * 70)
    return "\n".join(lines)


def format_json(summary: ScanSummary) -> str:
    """Format scan results as JSON."""
    return json.dumps(summary.to_dict(), indent=2)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze OpenCure Labs pipeline logs for errors and warnings.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Log files or directories to scan. Default: most recent genesis dir.",
    )
    parser.add_argument(
        "--latest-genesis",
        action="store_true",
        default=False,
        help="Scan the most recent genesis-* log directory.",
    )
    parser.add_argument(
        "--logs-dir",
        default="logs",
        help="Base directory containing log files (default: logs).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        default=False,
        help="Output results as JSON.",
    )
    parser.add_argument(
        "--severity",
        choices=["CRITICAL", "HIGH", "MEDIUM", "LOW"],
        default="MEDIUM",
        help="Minimum severity to show (default: MEDIUM).",
    )
    parser.add_argument(
        "--include-noise",
        action="store_true",
        default=False,
        help="Include LOW-severity dependency noise (CUDA, FutureWarning, etc.).",
    )

    args = parser.parse_args(argv)

    # Resolve paths to scan
    scan_paths: list[Path] = []

    if args.paths:
        scan_paths = [Path(p) for p in args.paths]
    elif args.latest_genesis or not args.paths:
        logs_dir = Path(args.logs_dir)
        if not logs_dir.is_dir():
            print(f"Error: logs directory not found: {logs_dir}", file=sys.stderr)
            return 1
        genesis_dir = find_latest_genesis(logs_dir)
        if genesis_dir:
            scan_paths = [genesis_dir]
        else:
            print("Error: no genesis-* directories found.", file=sys.stderr)
            return 1

    # Validate paths exist
    for p in scan_paths:
        if not p.exists():
            print(f"Error: path not found: {p}", file=sys.stderr)
            return 1

    # Run scan
    include_noise = args.include_noise or args.severity == "LOW"
    summary = scan(scan_paths, include_noise=include_noise, min_severity=args.severity)

    # Output
    if args.json_output:
        print(format_json(summary))
    else:
        print(format_text(summary))

    # Exit code: 2 if CRITICAL findings, 1 if HIGH findings, 0 otherwise
    by_sev = summary.by_severity
    if by_sev.get("CRITICAL", 0) > 0:
        return 2
    if by_sev.get("HIGH", 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
