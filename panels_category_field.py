"""Developer Portal -- the category picker shared by New App and Edit App.

Both forms used to render a FREE-TEXT input with the placeholder `tools`.
That is how the Marketplace ended up with `system` and `System` as two
different categories, `AI & Media` sitting next to `ai-media`, and a category
column nobody could group, translate or filter reliably.

The catalog is the gateway's (`GET /v1/marketplace/categories/catalog`), so a
category added there appears here with NO change to this extension. Labels
arrive already translated, so the picker follows the platform language for
free -- it never hard-codes English display text.

`ui.Select` is a FLAT list with no optgroup support, so each label carries its
group as a prefix (`AI - AI Agents`). With 111 categories that keeps the list
scannable and keeps every category of one group visually together.
"""
from imperal_sdk import ui
from app import _gw_get

# Used when the gateway is unreachable: the picker must still render something
# sane rather than blocking app creation entirely. Mirrors the gateway's own
# `default_category`.
_FALLBACK_CATEGORY = "productivity"

# Deliberately small -- this is a DEGRADED mode, not a second source of truth.
# A stale copy of all 111 categories here would be exactly the drift the
# canonical catalog exists to prevent.
_FALLBACK_OPTIONS = [
    {"value": "productivity", "label": "\u26a1 Productivity"},
    {"value": "developer-tools", "label": "\U0001f6e0 Developer Tools"},
    {"value": "ai-media", "label": "\U0001f3a8 AI Media Generation"},
    {"value": "marketing", "label": "\U0001f4e3 Marketing"},
    {"value": "web-analytics", "label": "\U0001f4c9 Web Analytics"},
    {"value": "messaging", "label": "\U0001f4ac Messaging & Chat"},
    {"value": "seo", "label": "\U0001f50d SEO"},
    {"value": "content-creation", "label": "\u270d Writing & Content"},
]


async def category_options(current: str = "") -> tuple[list[dict], str]:
    """Return (options, selected_value) for the category dropdown.

    `current` is the app's stored category, which for a third-party app is
    whatever its author typed (`tools`, `AI & Media`). Those rows are
    deliberately never migrated, so a legacy value that is not in the catalog
    is KEPT as an explicit extra option and pre-selected. Without that, opening
    Edit App would show some unrelated category as selected and a plain Save
    would silently recategorise a live app.
    """
    try:
        data = await _gw_get("/v1/marketplace/categories/catalog")
        groups = data.get("groups") or []
        options: list[dict] = []
        for group in groups:
            gname = group.get("name") or group.get("id") or ""
            for cat in group.get("categories") or []:
                cid = cat.get("id")
                if not cid:
                    continue
                icon = cat.get("icon") or ""
                name = cat.get("name") or cid
                label = f"{icon} {name}".strip()
                options.append({
                    "value": cid,
                    "label": f"{gname} - {label}" if gname else label,
                })
        default = data.get("default_category") or _FALLBACK_CATEGORY
    except Exception:
        # The picker must never be the reason an app cannot be created.
        options = list(_FALLBACK_OPTIONS)
        default = _FALLBACK_CATEGORY

    if not options:
        options = list(_FALLBACK_OPTIONS)

    known = {o["value"] for o in options}

    current = (current or "").strip()
    if not current:
        # New app: pre-select the catalog default rather than leaving the
        # dropdown blank, so a submit without touching it is still valid.
        return options, (default if default in known else options[0]["value"])

    if current in known:
        return options, current

    # Legacy / unknown value: surface it honestly at the top instead of
    # dropping it, so saving the form cannot change the app's category by
    # accident. Picking any real entry replaces it with a canonical id.
    options = [{
        "value": current,
        "label": f"{current} \u2014 current value (not in the catalog)",
    }] + options
    return options, current


async def category_field(current: str = ""):
    """The labelled category dropdown used by both portal forms."""
    options, selected = await category_options(current)
    return ui.Stack(children=[
        ui.Text("Category", variant="caption"),
        ui.Select(options=options, value=selected, param_name="category"),
        ui.Text(
            "Pick the closest fit -- this is how users filter the Marketplace.",
            variant="caption",
        ),
    ], gap=1)
