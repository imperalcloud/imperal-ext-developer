"""Developer Portal — validation report generator.

Merges static (filesystem) + runtime (subprocess) check results
into a unified report. Generates LLM-friendly markdown for chat
and structured data for the Deploy tab panel.
"""


def merge_results(static: dict, runtime: dict) -> dict:
    """Merge static + runtime validation results into unified report.

    Args:
        static: Result from validation.validate_extension()
        runtime: Result from validation_runtime.run_runtime_validation()

    Returns:
        Unified report with all checks, summary, and LLM report.
    """
    static_checks = static.get("checks", [])
    runtime_checks = runtime.get("checks", [])

    # Tag static checks with phase + severity
    # Critical blockers: structure + syntax + the on-disk manifest schema
    # (slice-9, 2026-07-17 — the manifest is the source of truth every
    # surface derives from; a schema-invalid one must not deploy). Audited:
    # all 29 currently-deployed manifests pass, so this blocks nobody today.
    _CRITICAL_STATIC = {"structure", "syntax", "manifest_schema"}
    for c in static_checks:
        c.setdefault("phase", "static")
        if not c.get("passed") and c.get("name") in _CRITICAL_STATIC:
            c.setdefault("severity", "critical")
        else:
            c.setdefault("severity", "warning")

    all_checks = static_checks + runtime_checks
    passed = sum(1 for c in all_checks if c.get("passed"))
    total = len(all_checks)

    critical_fails = [c for c in all_checks
                      if not c.get("passed") and c.get("severity") == "critical"]
    warning_fails = [c for c in all_checks
                     if not c.get("passed") and c.get("severity") == "warning"]

    if critical_fails:
        status = "failed"
    elif warning_fails:
        status = "warning"
    else:
        status = "passed"

    report = {
        "checks": all_checks,
        "passed": passed,
        "total": total,
        "status": status,
        "critical_count": len(critical_fails),
        "warning_count": len(warning_fails),
        "llm_report": _build_llm_report(all_checks, status, passed, total),
    }
    return report


def _build_llm_report(checks: list, status: str, passed: int, total: int) -> str:
    """Generate markdown report optimized for LLM chat debugging."""
    # Find app_id from ext_object check
    app_id = "unknown"
    version = ""
    for c in checks:
        if c.get("name") == "ext_object" and c.get("passed"):
            detail = c.get("detail", "")
            if " v" in detail:
                parts = detail.split(" v", 1)
                app_id = parts[0]
                version = parts[1]
            break

    lines = [f"## Extension Validation: {app_id} v{version}"]
    lines.append(f"**Result: {status.upper()} ({passed}/{total} checks)**\n")

    # Critical failures
    critical = [c for c in checks if not c.get("passed") and c.get("severity") == "critical"]
    if critical:
        lines.append("### CRITICAL — Must Fix")
        for c in critical:
            lines.append(f"- **{c.get('label', c.get('name', '?'))}**: {c.get('detail', '')}")
            if c.get("fix"):
                lines.append(f"  - Fix: {c['fix']}")
            if c.get("full_error"):
                # Include traceback for load errors
                lines.append(f"  ```\n  {c['full_error'][:400]}\n  ```")

    # Warnings
    warnings = [c for c in checks if not c.get("passed") and c.get("severity") == "warning"]
    if warnings:
        lines.append("\n### WARNINGS — Should Fix")
        for c in warnings:
            lines.append(f"- **{c.get('label', c.get('name', '?'))}**: {c.get('detail', '')}")
            if c.get("fix"):
                lines.append(f"  - Fix: {c['fix']}")

    # SDK rule summary (only passed rules with count > 1)
    sdk_warns = [c for c in checks if c.get("passed") and c.get("sdk_level") == "WARN"
                 and c.get("count", 0) > 1]
    if sdk_warns:
        lines.append("\n### SDK Recommendations")
        for c in sdk_warns:
            lines.append(f"- {c['sdk_rule']}: {c.get('detail', '')} ({c.get('count', 1)}x)")

    # Passed summary
    passed_checks = [c for c in checks if c.get("passed")]
    if passed_checks and status != "passed":
        lines.append(f"\n### Passed ({len(passed_checks)})")
        for c in passed_checks:
            if not c.get("sdk_rule"):  # skip verbose SDK lines
                lines.append(f"- {c.get('label', c.get('name', '?'))}: {c.get('detail', 'OK')}")

    return "\n".join(lines)
