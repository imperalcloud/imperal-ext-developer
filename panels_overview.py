"""Developer Portal — Overview tab builder."""
from imperal_sdk import ui
from imperal_sdk.ui.base import UINode
from app import _gw_get, EXTENSIONS_DIR
from queries import get_latest_deploy
from validation import get_disk_version
import os

_STATUS_COLORS = {"draft": "gray", "pending_review": "yellow", "active": "green", "suspended": "red"}


def _field(label_text: str, placeholder: str, param_name: str, value: str = ""):
    return ui.Stack(children=[
        ui.Text(label_text, variant="caption"),
        ui.Input(placeholder=placeholder, param_name=param_name, value=value),
    ], gap=1)


async def build_overview(uid: str, app_id: str, view: str = "", **kwargs):
    try:
        app = await _gw_get(f"/v1/developer/apps/{app_id}?user_id={uid}")
    except Exception as exc:
        return ui.Alert(title="Couldn't load this app",
                        message=f"{type(exc).__name__}: {exc}", type="error")
    status = app.get("status", "draft")

    # Edit form
    if view == "edit":
        return ui.Stack(children=[
            ui.Header(f"Edit — {app.get('display_name', app_id)}", level=2),
            ui.Text(f"App ID: {app_id}", variant="caption"),
            ui.Form(
                action="update_app_info",
                submit_label="Save Changes",
                defaults={
                    "app_id": app_id,
                    "display_name": app.get("display_name", ""),
                    "description": app.get("description", ""),
                    "short_description": app.get("short_description", "") or "",
                    "long_description": app.get("long_description", "") or "",
                    "category": app.get("category", "general"),
                    "git_url": app.get("git_url", ""),
                },
                children=[
                    _field("Display Name", "My Extension",
                           "display_name", app.get("display_name", "")),
                    _field("Description", "What does your extension do?",
                           "description", app.get("description", "")),
                    # Storefront copy (2026-08-08). These two are what the
                    # Marketplace actually renders; before this they were not
                    # editable here at all.
                    ui.Stack(children=[
                        ui.Text("Short Description — the line on your Marketplace card",
                                variant="caption"),
                        ui.Input(
                            placeholder="One line that sells your extension (max 200 chars)",
                            param_name="short_description",
                            value=app.get("short_description", "") or "",
                        ),
                        ui.Text("Leave empty and we'll use the first line of your Description.",
                                variant="caption"),
                    ], gap=1),
                    ui.Stack(children=[
                        ui.Text("Full Description — the write-up on your Marketplace page",
                                variant="caption"),
                        ui.TextArea(
                            placeholder="What it does, who it's for, what makes it good. Markdown welcome.",
                            param_name="long_description",
                            value=app.get("long_description", "") or "",
                            rows=8,
                        ),
                    ], gap=1),
                    _field("Category", "tools",
                           "category", app.get("category", "general")),
                    _field("Git URL (HTTPS)", "https://github.com/you/repo.git",
                           "git_url", app.get("git_url", "")),
                ],
            ),
            ui.Button(
                label="Cancel", variant="ghost",
                on_click=ui.Call("__panel__dashboard", app_id=app_id, tab="overview",
                                 period="", view="", page=""),
            ),
        ], gap=2)

    children = []

    # Header: real app icon (single source — same /apps/{id}/icon endpoint as
    # marketplace + sidebar) on a plate (the panel `appicon` node renders the
    # shared <AppIcon>, so monochrome/currentColor icons stay visible on dark) ·
    # title · status badge
    children.append(ui.Stack(direction="h", gap=2, children=[
        UINode(type="appicon", props={
            "app_id": app_id,
            "display_name": app.get("display_name", app_id),
        }),
        ui.Header(app.get("display_name", app_id), level=2),
        ui.Badge(status.replace("_", " ").title(), color=_STATUS_COLORS.get(status, "gray")),
    ]))

    # App info
    children.append(ui.KeyValue(items=[
        {"key": "App ID", "value": app_id},
        {"key": "Category", "value": app.get("category", "general")},
        {"key": "Git URL", "value": app.get("git_url", "—")},
        {"key": "Created", "value": app.get("created_at", "—")},
        {"key": "Info Changed", "value": (app.get("updated_at") or "—")[:19]},
        {"key": "Pricing", "value": app.get("pricing_model", "free")},
        {"key": "Revenue Split", "value": f"{app.get('revenue_split_dev', 70)}% dev"},
    ], columns=2))

    # Current Version — from disk + last deploy
    version_items = []
    disk = get_disk_version(os.path.join(EXTENSIONS_DIR, app_id))
    deploy = await get_latest_deploy(app_id)
    if disk or deploy:
        kv_items = []
        if disk and disk.get("version"):
            kv_items.append({"key": "Version", "value": f"v{disk['version']}"})
        if deploy:
            kv_items.append({"key": "Last Deploy", "value": deploy["deployed_at"][:19]})
            kv_items.append({"key": "Commit", "value": deploy["commit"]})
            kv_items.append({"key": "Deploy Status", "value": deploy["status"]})
        elif disk and disk.get("commit"):
            kv_items.append({"key": "Commit", "value": disk["commit"]})
        if kv_items:
            version_items.append(ui.KeyValue(items=kv_items, columns=2))
    if not version_items:
        version_items.append(ui.Text("Not deployed yet.", variant="caption"))
    children.append(ui.Section(title="Current Version", children=version_items))

    desc = app.get("description", "")
    if desc:
        children.append(ui.Section(title="Description", children=[ui.Text(desc)]))

    if app.get("reject_reason"):
        children.append(ui.Alert(title="Review Feedback", message=app["reject_reason"], type="error"))

    # Actions
    actions = []
    if status == "draft":
        actions.append(ui.Button(
            label="Edit Info", icon="Pencil", variant="secondary",
            on_click=ui.Call("__panel__dashboard", app_id=app_id, tab="overview",
                             period="", view="edit", page=""),
        ))
        actions.append(ui.Button(
            label="Deploy from Git", icon="Download", variant="primary",
            on_click=ui.Call("deploy_app", app_id=app_id),
        ))
        actions.append(ui.Button(
            label="Submit for Review", icon="Send", variant="secondary",
            on_click=ui.Call("submit_for_review", app_id=app_id),
        ))
    elif status == "pending_review":
        actions.append(ui.Alert(message="Waiting for admin review...", type="info"))
        actions.append(ui.Button(
            label="Pause App", icon="Pause", variant="ghost",
            on_click=ui.Call("suspend_app", app_id=app_id),
        ))
    elif status == "active":
        actions.append(ui.Alert(message="Your app is live!", type="info"))
        actions.append(ui.Stack(direction="h", gap=1, children=[
            ui.Button(
                label="Edit Info", icon="Pencil", variant="secondary",
                on_click=ui.Call("__panel__dashboard", app_id=app_id, tab="overview",
                                 period="", view="edit", page=""),
            ),
            ui.Button(
                label="Pull Latest", icon="RefreshCw", variant="secondary",
                on_click=ui.Call("deploy_app", app_id=app_id),
            ),
            ui.Button(
                label="Pause App", icon="Pause", variant="ghost",
                on_click=ui.Call("suspend_app", app_id=app_id),
            ),
        ]))
    elif status == "suspended":
        actions.append(ui.Button(
            label="Edit Info", icon="Pencil", variant="secondary",
            on_click=ui.Call("__panel__dashboard", app_id=app_id, tab="overview",
                             period="", view="edit", page=""),
        ))
        actions.append(ui.Button(
            label="Resubmit for Review", icon="Send", variant="primary",
            on_click=ui.Call("submit_for_review", app_id=app_id),
        ))

    # Delete available for suspended and draft apps
    if status in ("suspended", "draft"):
        actions.append(ui.Section(
            title="Danger Zone",
            children=[
                ui.Text(f"Permanently delete this app. Type '{app_id}' to confirm. This cannot be undone."),
                ui.Form(
                    action="delete_app",
                    submit_label="Delete App Permanently",
                    defaults={"app_id": app_id},
                    children=[
                        ui.Input(placeholder=f"Type '{app_id}' to confirm", param_name="confirm_name"),
                    ],
                ),
            ],
        ))

    if actions:
        children.append(ui.Section(
            title="Actions",
            children=[ui.Stack(direction="v", gap=1, children=actions)],
        ))

    return ui.Stack(children=children, gap=2)
