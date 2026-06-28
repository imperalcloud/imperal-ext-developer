"""Developer Portal — Skeleton timer tab. Edit per-section refresh interval.

The cadence is a global, developer-owned value: ttl_override (UI) over the
manifest ttl default. Effective ttl is served by the Registry as
COALESCE(ttl_override, ttl); "Default (manifest)" clears the override.
"""
from imperal_sdk import ui
from app import _gw_get, _registry_get
from skeleton_ttl import TTL_OPTIONS, human_interval


async def build_skeleton(uid: str, app_id: str, view: str = "", **kwargs):
    # Owner gate — the developer endpoint only returns the dev's own app.
    try:
        await _gw_get(f"/v1/developer/apps/{app_id}?user_id={uid}")
    except Exception as exc:
        return ui.Alert(title="Couldn't load app",
                        message=f"{type(exc).__name__}: {exc}", type="error")
    # Read sections (default ttl + override) from the Registry.
    try:
        settings = await _registry_get(f"/v1/apps/{app_id}/settings")
    except Exception as exc:
        return ui.Alert(title="Couldn't load skeleton config",
                        message=f"{type(exc).__name__}: {exc}", type="error")
    sections = (settings.get("skeleton") or {}).get("sections", [])

    if not sections:
        return ui.Stack(children=[
            ui.Section(title="Skeleton Monitors", children=[
                ui.Alert(type="info",
                         message="This app has no skeleton sections. Declare one with "
                                 "@ext.skeleton(\"name\", ttl=300) and deploy."),
            ]),
        ], gap=2)

    def _effective(s):
        ov = s.get("ttl_override")
        return ov if ov is not None else s.get("ttl", 300)

    # Edit form
    if view == "edit":
        form_children = [ui.Text("Refresh interval per section", variant="caption")]
        defaults = {"app_id": app_id}
        for s in sections:
            name = s["section_name"]
            ov = s.get("ttl_override")
            cur_value = "default" if ov is None else str(ov)
            defaults[f"ttl_{name}"] = cur_value
            form_children.append(ui.Stack(direction="h", gap=1, children=[
                ui.Text(name, variant="caption"),
                ui.Select(param_name=f"ttl_{name}", value=cur_value, options=TTL_OPTIONS),
            ]))
        return ui.Stack(children=[
            ui.Header("Edit Skeleton Timers", level=2),
            ui.Form(action="save_skeleton_ttl", submit_label="Save Timers",
                    defaults=defaults, children=form_children),
            ui.Button(label="Cancel", variant="ghost",
                      on_click=ui.Call("__panel__dashboard", app_id=app_id, tab="skeleton",
                                       period="", view="", page="")),
        ], gap=2)

    # Display
    rows = []
    for s in sections:
        ov = s.get("ttl_override")
        rows.append({
            "section": s["section_name"],
            "interval": human_interval(_effective(s)),
            "source": "overridden" if ov is not None else "default",
        })
    return ui.Stack(children=[
        ui.Section(title="Skeleton Monitors", children=[
            ui.Text("How often each background section refreshes. This is your app's "
                    "default for all users; overrides survive redeploys.", variant="caption"),
            ui.DataTable(
                columns=[
                    ui.DataColumn(key="section", label="Section", width="50%"),
                    ui.DataColumn(key="interval", label="Interval", width="25%"),
                    ui.DataColumn(key="source", label="Source", width="25%"),
                ],
                rows=rows,
            ),
            ui.Button(label="Edit Timers", icon="Pencil", variant="primary",
                      on_click=ui.Call("__panel__dashboard", app_id=app_id, tab="skeleton",
                                       period="", view="edit", page="")),
        ]),
    ], gap=2)
