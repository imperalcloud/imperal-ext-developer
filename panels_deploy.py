"""Developer Portal — Deploy tab builder."""
import json
import os
from imperal_sdk import ui
from app import _gw_get, EXTENSIONS_DIR
from queries import get_deploy_history, get_latest_deploy
from validation import get_disk_version


def _parse_validation(error_msg: str) -> list | None:
    if not error_msg:
        return None
    try:
        data = json.loads(error_msg)
        return data.get("checks") if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _severity_color(check: dict) -> str:
    if check.get("passed"):
        return "green"
    sev = check.get("severity", "warning")
    return "red" if sev == "critical" else "yellow"


def _severity_label(check: dict) -> str:
    if check.get("passed"):
        return "PASS"
    sev = check.get("severity", "warning")
    return "FAIL" if sev == "critical" else "WARN"


def _build_phase_section(title: str, checks: list) -> ui.Section:
    """Build a section for one validation phase."""
    items = []
    for c in checks:
        color = _severity_color(c)
        label = _severity_label(c)
        detail = c.get("detail", "")

        row_children = [
            ui.Badge(label, color=color),
            ui.Text(c.get("label", c.get("name", "")), variant="caption"),
        ]
        items.append(ui.Stack(direction="h", gap=1, children=row_children))

        # Show detail on separate line for failed checks
        if not c.get("passed") and detail:
            detail_children = [ui.Text(f"  {detail}", variant="caption")]
            if c.get("fix"):
                detail_children.append(
                    ui.Text(f"  Fix: {c['fix']}", variant="caption")
                )
            items.append(ui.Stack(children=detail_children, gap=0))

    passed = sum(1 for c in checks if c.get("passed"))
    return ui.Section(
        title=f"{title} ({passed}/{len(checks)})",
        children=items if items else [ui.Text("No checks", variant="caption")],
    )


def _build_report(checks: list) -> list:
    """Build full validation report with phase grouping."""
    static = [c for c in checks if c.get("phase") == "static"]
    runtime = [c for c in checks if c.get("phase") == "runtime"]

    sections = []

    # Summary alert
    all_passed = sum(1 for c in checks if c.get("passed"))
    critical_fails = [c for c in checks
                      if not c.get("passed") and c.get("severity") == "critical"]
    warning_fails = [c for c in checks
                     if not c.get("passed") and c.get("severity") == "warning"]

    if critical_fails:
        alert_type = "error"
        msg = f"FAILED — {len(critical_fails)} critical issue(s), {len(warning_fails)} warning(s)"
    elif warning_fails:
        alert_type = "warning"
        msg = f"Deployed with {len(warning_fails)} warning(s)"
    else:
        alert_type = "info"
        msg = f"All {len(checks)} checks passed"

    sections.append(ui.Alert(type=alert_type, message=f"Validation: {all_passed}/{len(checks)} — {msg}"))

    if static:
        sections.append(_build_phase_section("Phase 1: Static Analysis", static))
    if runtime:
        sections.append(_build_phase_section("Phase 2: Runtime Validation", runtime))

    return sections


async def build_deploy(uid: str, app_id: str, **kwargs):
    try:
        app = await _gw_get(f"/v1/developer/apps/{app_id}?user_id={uid}")
    except Exception as exc:
        return ui.Alert(type="error", message=f"Failed to load app: {exc}")

    status = app.get("status", "draft")
    git_url = app.get("git_url", "")
    children = []

    # Active Version block
    disk = get_disk_version(os.path.join(EXTENSIONS_DIR, app_id))
    deploy = await get_latest_deploy(app_id)

    version_items = []
    if disk or deploy:
        kv = []
        if disk and disk.get("version"):
            kv.append({"key": "Active Version", "value": f"v{disk['version']}"})
        if disk and disk.get("commit"):
            kv.append({"key": "Commit on Disk", "value": disk["commit"]})
        if deploy:
            kv.append({"key": "Last Deployed", "value": deploy["deployed_at"][:19]})
            kv.append({"key": "Deploy Commit", "value": deploy["commit"]})
            kv.append({"key": "Deploy Result", "value": deploy["status"]})
        if kv:
            version_items.append(ui.KeyValue(items=kv, columns=2))
    if not version_items:
        version_items.append(ui.Text("Not deployed yet.", variant="caption"))
    children.append(ui.Section(title="Active Version", children=version_items))

    # Git URL + deploy button
    children.append(ui.KeyValue(items=[
        {"key": "Git URL", "value": git_url or "Not configured"},
    ], columns=1))

    if not git_url:
        children.append(ui.Alert(type="info", message="Set a Git URL first (Edit Info in Overview tab)."))
    else:
        if status == "active":
            children.append(ui.Alert(type="info", message="Live app — test thoroughly before deploying."))
        children.append(ui.Button(
            label="Pull and Deploy", icon="Rocket", variant="primary",
            on_click=ui.Call("deploy_app", app_id=app_id),
        ))

    # Deploy history with validation
    try:
        history = await get_deploy_history(app_id, limit=10)
    except Exception:
        history = []

    if history:
        latest = history[0]
        checks = _parse_validation(latest.get("error", ""))

        if checks:
            children.append(ui.Section(
                title=f"Last Deploy — {latest['sha']} ({latest['status']})",
                children=[
                    ui.Text(f"Deployed: {latest['date'][:19]}", variant="caption"),
                ] + _build_report(checks),
            ))
        elif latest.get("error") and latest["status"] == "failed":
            children.append(ui.Section(
                title=f"Last Deploy — {latest['sha']} (failed)",
                children=[
                    ui.Alert(type="error", message=latest["error"][:300]),
                    ui.Text(f"Deployed: {latest['date'][:19]}", variant="caption"),
                ],
            ))

        # History table
        rows = []
        for h in history:
            h_checks = _parse_validation(h.get("error", ""))
            if h_checks:
                p = sum(1 for c in h_checks if c.get("passed"))
                t = len(h_checks)
                val_col = f"{p}/{t}"
            else:
                val_col = (h.get("error", "") or "")[:40] or "-"
            rows.append({
                "sha": h["sha"],
                "status": h["status"],
                "validation": val_col,
                "date": h["date"][:19] if h["date"] else "",
            })

        children.append(ui.Section(title=f"Deploy History ({len(history)})", children=[
            ui.DataTable(
                columns=[
                    ui.DataColumn(key="sha", label="Commit", width="18%"),
                    ui.DataColumn(key="status", label="Status", width="18%"),
                    ui.DataColumn(key="validation", label="Checks", width="30%"),
                    ui.DataColumn(key="date", label="Date", width="34%"),
                ],
                rows=rows,
            ),
        ]))
    else:
        children.append(ui.Text("No deploys yet. Click 'Pull and Deploy' to start.", variant="caption"))

    # Validation info
    children.append(ui.Section(title="Validation Pipeline", children=[
        ui.Text(
            "Each deploy runs a 2-phase validation pipeline:\n\n"
            "Phase 1 — Static Analysis (6 checks):\n"
            "  1. Structure — main.py exists\n"
            "  2. Manifest — imperal.json valid\n"
            "  3. Syntax — all .py files compile\n"
            "  4. File size — no file > 300 lines\n"
            "  5. Security — no dangerous patterns\n"
            "  6. SDK usage — imports imperal_sdk\n\n"
            "Phase 2 — Runtime Validation (7+ checks):\n"
            "  R1. Load — main.py imports successfully\n"
            "  R2. Extension object found\n"
            "  R3. SDK rules V1-V12 (contract compliance)\n"
            "  R4. Panels — at least one sidebar panel\n"
            "  R5. Manifest sync — tools match code\n"
            "  R6. Chat functions registered\n"
            "  R7. Import chain — all dependencies resolve\n"
            "  R8. DUI components — valid params (catches ui.Form(variant=...) etc)\n"
            "  R9. Extension tests — runs pytest if tests/ exists",
            variant="caption",
        ),
    ]))

    return ui.Stack(children=children, gap=2)
