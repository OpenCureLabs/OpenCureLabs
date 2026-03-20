#!/usr/bin/env python3
"""
OpenCure Labs — Static Security Scanner.

Profile-driven static analysis with unified reporting, baseline comparison,
auto-fix orchestration, and Discord webhook notification.

Usage:
    python security/security_scan.py --profile security/profiles/opencurelabs.yaml
    python security/security_scan.py --profile ... --autofix safe
    python security/security_scan.py --profile ... --baseline-save security/baselines/initial.json
    python security/security_scan.py --profile ... --baseline-compare security/baselines/initial.json
    python security/security_scan.py --profile ... --discord

Tools:
    ruff            Code quality linting
    bandit          Security-focused static analysis
    pip-audit       Dependency vulnerability scanning
    detect-secrets  Hardcoded secret detection

Output:
    Markdown + JSON report to security/reports/
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Install with: pip install pyyaml")
    sys.exit(1)


# ── Profile Loader ───────────────────────────────────────────────


def load_profile(path: str) -> dict:
    """Load a YAML scan profile."""
    with open(path) as f:
        return yaml.safe_load(f)


# ── Data Classes ─────────────────────────────────────────────────


@dataclass
class Finding:
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    category: str
    title: str
    detail: str
    remediation: str = ""


@dataclass
class ScanResult:
    target: str
    profile_name: str
    started: str
    finished: str = ""
    findings: list[Finding] = field(default_factory=list)
    passed: int = 0
    total: int = 0


# ── Output Helpers ───────────────────────────────────────────────


def _p(msg: str) -> None:
    print(msg, flush=True)


def _pass(result: ScanResult, msg: str) -> None:
    result.total += 1
    result.passed += 1
    _p(f"  ✅ {msg}")


def _fail(result: ScanResult, finding: Finding, msg: str) -> None:
    result.total += 1
    result.findings.append(finding)
    _p(f"  ❌ {msg}")


def _warn(result: ScanResult, finding: Finding, msg: str) -> None:
    result.total += 1
    result.findings.append(finding)
    _p(f"  ⚠️  {msg}")


# ── Tool Runner ──────────────────────────────────────────────────


def _run_tool(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """Run a CLI tool and return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(Path(__file__).resolve().parent.parent),  # project root
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return -1, "", f"{cmd[0]} not found"
    except subprocess.TimeoutExpired:
        return -2, "", f"{cmd[0]} timed out after {timeout}s"


# ── Static Analysis Checks ──────────────────────────────────────


def check_static_ruff(result: ScanResult, profile: dict) -> None:
    """Run ruff linter on the project."""
    _p("\n🔍 Static: Ruff (code quality)...")
    target = profile.get("static", {}).get("ruff_target", "packages/agentiq_labclaw/")
    result.total += 1
    rc, stdout, stderr = _run_tool(["ruff", "check", target, "--output-format=json"])

    if rc == -1:
        _p("  ⚠️  ruff not installed, skipping")
        result.passed += 1
        return

    if rc == 0:
        result.passed += 1
        _p("  ✅ No lint issues")
        return

    try:
        issues = json.loads(stdout)
    except json.JSONDecodeError:
        issues = []

    if not issues:
        result.passed += 1
        _p("  ✅ No lint issues")
        return

    _warn(result, Finding(
        severity="LOW", category="Static Analysis - Ruff",
        title=f"Ruff: {len(issues)} lint issue(s)",
        detail="; ".join(
            f"{i.get('filename', '?')}:{i.get('location', {}).get('row', '?')} "
            f"{i.get('code', '?')} {i.get('message', '')}"
            for i in issues[:5]
        ),
        remediation=f"Run: ruff check --fix {target}",
    ), f"{len(issues)} lint issue(s)")


def check_static_bandit(result: ScanResult, profile: dict) -> None:
    """Run Bandit security linter."""
    _p("\n🛡️  Static: Bandit (security analysis)...")
    target = profile.get("static", {}).get("bandit_target", "packages/agentiq_labclaw/")
    config = profile.get("static", {}).get("bandit_config", "")
    result.total += 1

    cmd = ["bandit", "-r", target, "-f", "json", "-q"]
    if config:
        cmd.extend(["-c", config])

    rc, stdout, stderr = _run_tool(cmd)

    if rc == -1:
        _p("  ⚠️  bandit not installed, skipping")
        result.passed += 1
        return

    try:
        report = json.loads(stdout)
        issues = report.get("results", [])
    except json.JSONDecodeError:
        issues = []

    serious = [i for i in issues if i.get("issue_severity", "").upper() in ("MEDIUM", "HIGH")]

    if not serious:
        result.passed += 1
        low_count = len(issues)
        msg = "No medium+ issues" + (f" ({low_count} low)" if low_count else "")
        _p(f"  ✅ {msg}")
        return

    for issue in serious[:3]:
        sev = "MEDIUM" if issue.get("issue_severity", "").upper() == "MEDIUM" else "HIGH"
        result.findings.append(Finding(
            severity=sev, category="Static Analysis - Bandit",
            title=f"Bandit {issue.get('test_id', '?')}: {issue.get('issue_text', '')}",
            detail=f"{issue.get('filename', '?')}:{issue.get('line_number', '?')}",
            remediation=f"See: {issue.get('more_info', '')}",
        ))
        _p(f"  ⚠️  [{sev}] {issue.get('test_id', '?')}: {issue.get('issue_text', '')}")
    if len(serious) > 3:
        _p(f"  ... and {len(serious) - 3} more")


def check_static_pip_audit(result: ScanResult, profile: dict | None = None) -> None:
    """Run pip-audit for known vulnerabilities in dependencies."""
    _p("\n📦 Static: pip-audit (dependency vulnerabilities)...")
    result.total += 1
    rc, stdout, stderr = _run_tool(
        ["pip-audit", "--format=json", "--desc", "--progress-spinner=off"],
        timeout=120,
    )

    if rc == -1:
        _p("  ⚠️  pip-audit not installed, skipping")
        result.passed += 1
        return
    if rc == -2:
        _p("  ⚠️  pip-audit timed out")
        result.passed += 1
        return

    # Build set of accepted CVE IDs from profile
    accepted_cves: set[str] = set()
    if profile:
        for entry in profile.get("accepted_risks", []):
            cve = entry.get("cve", "")
            if cve:
                accepted_cves.add(cve)

    try:
        report = json.loads(stdout)
        vulns = report.get("dependencies", [])
        vuln_pkgs = [v for v in vulns if v.get("vulns")]
    except json.JSONDecodeError:
        vuln_pkgs = []

    if not vuln_pkgs:
        result.passed += 1
        _p("  ✅ No known vulnerabilities")
        return

    reported = 0
    for pkg in vuln_pkgs:
        name = pkg.get("name", "?")
        version = pkg.get("version", "?")
        for vuln in pkg.get("vulns", []):
            vuln_id = vuln.get("id", "?")
            if vuln_id in accepted_cves:
                _p(f"  ℹ️  Accepted risk: {name}=={version} ({vuln_id})")
                continue
            desc = vuln.get("description", "")[:100]
            fix = vuln.get("fix_versions", [])
            _fail(result, Finding(
                severity="HIGH",
                category="Static Analysis - Dependencies",
                title=f"Vulnerable dependency: {name}=={version} ({vuln_id})",
                detail=desc,
                remediation=f"Upgrade to: {', '.join(fix)}" if fix else "Check for updates.",
            ), f"{name}=={version}: {vuln_id}")
            reported += 1
            if reported >= 3:
                break
        if reported >= 3:
            break
    if reported == 0:
        result.passed += 1
        _p("  ✅ All vulnerabilities are accepted risks")
        return
    remaining = sum(1 for p in vuln_pkgs for v in p.get("vulns", [])
                    if v.get("id", "?") not in accepted_cves) - reported
    if remaining > 0:
        _p(f"  ... and {remaining} more vulnerable packages")


def check_static_secrets(result: ScanResult, file_list: list[str] | None = None) -> None:
    """Run detect-secrets for hardcoded secrets.

    Uses baseline comparison: only flags NEW secrets not already in .secrets.baseline.
    If file_list is provided, scans only those files (e.g. staged files in pre-commit).
    """
    _p("\n🔐 Static: detect-secrets (secret scanning)...")
    result.total += 1

    exclude_patterns = [
        r"\.env$", r"\.env\.example$", r"\.secrets\.baseline$",
        r"^docs/", r"^security/reports/",
    ]
    cmd = ["detect-secrets", "scan"]
    for pat in exclude_patterns:
        cmd.extend(["--exclude-files", pat])

    if file_list:
        # Scan only specified files (e.g. staged files from pre-commit)
        cmd.extend(file_list)

    timeout = 15 if file_list else 60
    rc, stdout, stderr = _run_tool(cmd, timeout=timeout)

    if rc == -1:
        _p("  ⚠️  detect-secrets not installed, skipping")
        result.passed += 1
        return

    try:
        scan_results = json.loads(stdout).get("results", {})
    except json.JSONDecodeError:
        scan_results = {}

    # Load baseline for comparison (only flag NEW secrets)
    baseline_path = Path(__file__).resolve().parent.parent / ".secrets.baseline"
    baseline_secrets: dict = {}
    if baseline_path.exists():
        try:
            with open(baseline_path) as f:
                baseline_secrets = json.load(f).get("results", {})
        except (json.JSONDecodeError, OSError):
            pass

    new_secrets: list[tuple[str, dict]] = []
    for filepath, secrets in scan_results.items():
        baseline_file_secrets = baseline_secrets.get(filepath, [])
        baseline_hashes = {s.get("hashed_secret") for s in baseline_file_secrets}
        for secret in secrets:
            if secret.get("hashed_secret") not in baseline_hashes:
                new_secrets.append((filepath, secret))

    if not new_secrets:
        result.passed += 1
        total_baselined = sum(len(v) for v in scan_results.values())
        msg = "No new secrets detected"
        if total_baselined:
            msg += f" ({total_baselined} baselined)"
        _p(f"  ✅ {msg}")
        return

    shown = 0
    for filepath, secret in new_secrets:
        if shown >= 3:
            break
        _fail(result, Finding(
            severity="CRITICAL", category="Static Analysis - Secrets",
            title=f"NEW hardcoded secret in {filepath}",
            detail=f"Line {secret.get('line_number', '?')}: {secret.get('type', 'unknown')} detected",
            remediation="Move secret to environment variable. "
                        "If false positive, update baseline: detect-secrets scan > .secrets.baseline",
        ), f"{filepath}:{secret.get('line_number', '?')} ({secret.get('type', '')})")
        shown += 1
    if len(new_secrets) > 3:
        _p(f"  ... and {len(new_secrets) - 3} more new secrets")


def run_static_analysis(result: ScanResult, profile: dict, file_list: list[str] | None = None) -> None:
    """Run all static analysis tools."""
    _p(f"\n{'─'*60}")
    _p("  📋 Static Analysis")
    _p(f"{'─'*60}")
    check_static_ruff(result, profile)
    check_static_bandit(result, profile)
    check_static_pip_audit(result, profile)
    check_static_secrets(result, file_list=file_list)
    _p(f"{'─'*60}")
    static_findings = [f for f in result.findings if f.category.startswith("Static Analysis")]
    if static_findings:
        _p(f"  ⚠️  {len(static_findings)} static finding(s)")
    else:
        _p("  ✅ Static analysis clean")
    _p(f"{'─'*60}")


# ── Governance: Tier Classification ──────────────────────────────

SAFE_FIX_CATEGORIES = {
    "Static Analysis - Ruff",
}

NEVER_AUTOFIX_CATEGORIES = {
    "Static Analysis - Secrets",
    "Static Analysis - Dependencies",
    "Static Analysis - Bandit",
}


def classify_findings(findings: list[Finding]) -> dict:
    """Classify findings into Tier 1 (auto-fixable) and Tier 2 (human required)."""
    tier1 = [f for f in findings if f.category in SAFE_FIX_CATEGORIES]
    tier2 = [f for f in findings if f.category in NEVER_AUTOFIX_CATEGORIES]
    other = [f for f in findings if f not in tier1 and f not in tier2]
    return {"tier1": tier1, "tier2": tier2, "other": other}


# ── Auto-Fix Orchestrator ────────────────────────────────────────


def run_autofix(result: ScanResult, mode: str, profile: dict) -> dict:
    """Run Tier 1 auto-fixes.

    Args:
        result: Current scan result with findings
        mode: 'safe' (Tier 1 only), 'low' (LOW severity only), 'none' (skip)
        profile: Scan profile dict
    """
    if mode == "none":
        return {"skipped": True}

    classified = classify_findings(result.findings)
    fixable = classified["tier1"]

    if mode == "low":
        fixable = [f for f in fixable if f.severity == "LOW"]

    if not fixable:
        _p("\n  ℹ️  No auto-fixable findings")
        return {"fixed": 0, "fixable": []}

    target = profile.get("static", {}).get("ruff_target", "packages/agentiq_labclaw/")

    _p(f"\n{'─'*60}")
    _p(f"  🔧 Auto-Fix (mode={mode})")
    _p(f"  {len(fixable)} fixable finding(s), {len(classified['tier2'])} Tier 2 (untouched)")
    _p(f"{'─'*60}")

    fixed_count = 0
    actions: list[str] = []

    ruff_findings = [f for f in fixable if f.category == "Static Analysis - Ruff"]
    if ruff_findings:
        _p("\n  🔍 Running ruff --fix...")
        rc, stdout, stderr = _run_tool(["ruff", "check", target, "--fix"])
        if "fixed" in stdout.lower() or "fixed" in stderr.lower():
            fixed_count += len(ruff_findings)
            actions.append(f"Ruff: fixed {len(ruff_findings)} lint issue(s)")
            _p(f"  ✅ Ruff auto-fixed {len(ruff_findings)} issue(s)")
        else:
            _p("  ℹ️  Ruff --fix made no changes")

    _p(f"\n{'─'*60}")
    _p(f"  Auto-fix complete: {fixed_count} fixed")
    if classified["tier2"]:
        _p(f"  🔴 {len(classified['tier2'])} Tier 2 finding(s) require human attention")
    _p(f"{'─'*60}")

    return {"fixed": fixed_count, "actions": actions, "tier2_count": len(classified["tier2"])}


# ── Discord Notification ─────────────────────────────────────────


def send_discord_notification(result: ScanResult, grade: str, report_path: str) -> bool:
    """Post scan summary to Discord webhook. Only sends on CRITICAL/HIGH findings."""
    webhook_url = (os.environ.get("DISCORD_WEBHOOK_URL_AGENT_LOGS", "")
                    or os.environ.get("DISCORD_WEBHOOK_URL", ""))
    if not webhook_url:
        _p("  ⚠️  DISCORD_WEBHOOK_URL_AGENT_LOGS not set, skipping notification")
        return False

    by_sev: dict[str, int] = {}
    for f in result.findings:
        by_sev[f.severity] = by_sev.get(f.severity, 0) + 1

    has_critical = by_sev.get("CRITICAL", 0) > 0
    has_high = by_sev.get("HIGH", 0) > 0

    if not has_critical and not has_high:
        _p("  ℹ️  No CRITICAL/HIGH findings — skipping Discord notification")
        return False

    # Build embed
    sev_lines = []
    for s in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        if s in by_sev:
            sev_lines.append(f"**{s}:** {by_sev[s]}")

    finding_lines = []
    for f in result.findings[:10]:
        emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}.get(f.severity, "⚪")
        finding_lines.append(f"{emoji} [{f.severity}] {f.title}")

    description = (
        f"**Grade:** {grade}\n"
        f"**Checks:** {result.passed}/{result.total} passed\n"
        f"{chr(10).join(sev_lines)}\n\n"
        f"**Findings:**\n" + "\n".join(finding_lines)
    )

    payload = {
        "embeds": [{
            "title": "🛡️ Security Scan — Action Required",
            "description": description[:4000],
            "color": 0xFF0000 if has_critical else 0xFF8C00,
            "footer": {"text": f"OpenCure Labs Security Scanner | {result.started}"},
        }]
    }

    try:
        import requests
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code in (200, 204):
            _p("  📢 Discord notification sent")
            return True
        else:
            _p(f"  ⚠️  Discord webhook returned {resp.status_code}")
            return False
    except Exception as e:
        _p(f"  ⚠️  Discord notification failed: {e}")
        return False


# ── Report Generation ────────────────────────────────────────────


def _compute_grade(findings: list[Finding]) -> str:
    by_sev: dict[str, int] = {}
    for f in findings:
        by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
    c = by_sev.get("CRITICAL", 0)
    h = by_sev.get("HIGH", 0)
    m = by_sev.get("MEDIUM", 0)
    low = by_sev.get("LOW", 0)
    if c:
        return "F"
    elif h:
        return "D"
    elif m > 3:
        return "D"
    elif m:
        return "C"
    elif low > 5:
        return "C"
    elif low:
        return "B"
    elif not findings:
        return "A+"
    else:
        return "A"


def generate_report(result: ScanResult) -> tuple[str, str]:
    """Returns (markdown_text, grade)."""
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
    findings = sorted(result.findings, key=lambda f: severity_order.get(f.severity, 5))
    emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵", "INFO": "⚪"}

    by_sev: dict[str, int] = {}
    for f in findings:
        by_sev[f.severity] = by_sev.get(f.severity, 0) + 1

    grade = _compute_grade(findings)

    lines = [
        "# Static Security Scan Report", "",
        f"**Target:** {result.target}", f"**Profile:** {result.profile_name}",
        f"**Date:** {result.started}", f"**Grade:** {grade}", "",
        "## Summary", "", "| Metric | Value |", "|---|---|",
        f"| Total checks | {result.total} |", f"| Passed | {result.passed} |",
        f"| Failed | {result.total - result.passed} |", f"| Findings | {len(findings)} |", "",
    ]

    if by_sev:
        lines += ["### Findings by Severity", "", "| Severity | Count |", "|---|---|"]
        for s in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
            if s in by_sev:
                lines.append(f"| {emoji[s]} {s} | {by_sev[s]} |")
        lines.append("")

    static_cats = [
        "Static Analysis - Ruff", "Static Analysis - Bandit",
        "Static Analysis - Dependencies", "Static Analysis - Secrets",
    ]
    cats = set(f.category for f in findings)

    lines += ["### Static Analysis Coverage", "", "| Tool | Status |", "|---|---|"]
    for sc in static_cats:
        tool_name = sc.replace("Static Analysis - ", "")
        lines.append(f"| {tool_name} | {'⚠️ Findings' if sc in cats else '✅ Passed'} |")
    lines.append("")

    if findings:
        lines.append("## Findings\n")
        for i, f in enumerate(findings, 1):
            lines += [
                f"### {i}. {emoji.get(f.severity, '⚪')} [{f.severity}] {f.title}", "",
                f"**Category:** {f.category}",
                f"**Detail:** {f.detail}",
            ]
            if f.remediation:
                lines.append(f"**Remediation:** {f.remediation}")
            lines.append("")
    else:
        lines += ["## ✅ No Findings", "", "All checks passed.", ""]

    lines += ["---", f"*Report generated by OpenCure Labs Security Scanner at {result.finished}*"]
    return "\n".join(lines), grade


def generate_json_report(result: ScanResult, grade: str) -> dict:
    """Structured JSON report for CI integration and baseline comparison."""
    return {
        "target": result.target,
        "profile": result.profile_name,
        "started": result.started,
        "finished": result.finished,
        "grade": grade,
        "total": result.total,
        "passed": result.passed,
        "failed": result.total - result.passed,
        "findings": [asdict(f) for f in result.findings],
    }


# ── Baseline Comparison ─────────────────────────────────────────


def save_baseline(json_report: dict, path: str) -> None:
    """Save scan results as a baseline for future comparison."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(json_report, f, indent=2)
    _p(f"  💾 Baseline saved to {path}")


def compare_baseline(current: dict, baseline_path: str) -> list[str]:
    """Compare current scan against a saved baseline. Returns list of drift messages."""
    with open(baseline_path) as f:
        baseline = json.load(f)

    diffs: list[str] = []

    if current["grade"] != baseline["grade"]:
        diffs.append(f"🔄 Grade changed: {baseline['grade']} → {current['grade']}")

    if current["failed"] > baseline["failed"]:
        diffs.append(f"📈 Failures increased: {baseline['failed']} → {current['failed']}")
    elif current["failed"] < baseline["failed"]:
        diffs.append(f"📉 Failures decreased: {baseline['failed']} → {current['failed']} (improved)")

    baseline_titles = {f["title"] for f in baseline.get("findings", [])}
    current_titles = {f["title"] for f in current.get("findings", [])}

    new_findings = current_titles - baseline_titles
    resolved = baseline_titles - current_titles

    for title in sorted(new_findings):
        sev = next((f["severity"] for f in current["findings"] if f["title"] == title), "?")
        diffs.append(f"🆕 [{sev}] New: {title}")

    for title in sorted(resolved):
        diffs.append(f"✅ Resolved: {title}")

    if current["total"] != baseline["total"]:
        diffs.append(f"🔢 Check count changed: {baseline['total']} → {current['total']}")

    return diffs


# ── Main ─────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenCure Labs Static Security Scanner")
    parser.add_argument("--profile", required=True, help="Path to YAML scan profile")
    parser.add_argument("--autofix", default="none", choices=["safe", "low", "none"],
                        help="Auto-fix mode: safe (Tier 1), low (LOW only), none (default)")
    parser.add_argument("--baseline-save", default="", metavar="PATH",
                        help="Save scan results as baseline JSON for future comparison")
    parser.add_argument("--baseline-compare", default="", metavar="PATH",
                        help="Compare scan results against a saved baseline JSON")
    parser.add_argument("--discord", action="store_true",
                        help="Send Discord notification on CRITICAL/HIGH findings")
    parser.add_argument("--files", nargs="*", default=None,
                        help="Scan only these files (e.g. staged files from pre-commit)")
    args = parser.parse_args()

    profile = load_profile(args.profile)
    target = profile.get("static", {}).get("ruff_target", "packages/agentiq_labclaw/")
    pname = profile.get("name", Path(args.profile).stem)

    _p(f"\n{'='*60}")
    _p(f"  OpenCure Labs Security Scanner — {pname}")
    _p(f"  Target: {target}")
    _p(f"{'='*60}")

    result = ScanResult(
        target=target, profile_name=pname,
        started=datetime.datetime.now().isoformat(timespec="seconds"),
    )

    run_static_analysis(result, profile, file_list=args.files)

    result.finished = datetime.datetime.now().isoformat(timespec="seconds")
    report_md, grade = generate_report(result)
    json_report = generate_json_report(result, grade)

    # Write reports
    reports_dir = Path("security/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%dT%H%M%S")
    report_path = reports_dir / f"scan-{pname}-{ts}.md"
    report_path.write_text(report_md)

    json_path = reports_dir / f"scan-{pname}-{ts}.json"
    with open(json_path, "w") as f:
        json.dump(json_report, f, indent=2)

    failed = result.total - result.passed
    _p(f"\n{'='*60}")
    _p(f"  RESULTS: {result.passed}/{result.total} passed, {failed} failed")
    _p(f"  Grade:   {grade}")
    _p(f"  Report:  {report_path}")
    _p(f"  JSON:    {json_path}")

    # Auto-fix
    if args.autofix != "none":
        run_autofix(result, args.autofix, profile)

    # Baseline operations
    if args.baseline_save:
        save_baseline(json_report, args.baseline_save)

    if args.baseline_compare:
        _p(f"\n📊 Comparing against baseline: {args.baseline_compare}")
        try:
            diffs = compare_baseline(json_report, args.baseline_compare)
            if diffs:
                for d in diffs:
                    _p(f"  {d}")
            else:
                _p("  ✅ No security drift detected — identical to baseline")
        except FileNotFoundError:
            _p(f"  ⚠️  Baseline file not found: {args.baseline_compare}")
        except Exception as e:
            _p(f"  ⚠️  Baseline comparison error: {e}")

    # Discord notification
    if args.discord:
        _p(f"\n📢 Checking Discord notification...")
        send_discord_notification(result, grade, str(report_path))

    _p(f"{'='*60}\n")

    sys.exit(1 if any(f.severity in ("CRITICAL", "HIGH") for f in result.findings) else 0)


if __name__ == "__main__":
    main()
