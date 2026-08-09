"""The New App / Edit App category picker.

Both forms used to render a FREE-TEXT input, which is how the Marketplace
collected `system` next to `System` and `tools` next to `AI & Media`. These
tests pin the three properties that make the dropdown safe to ship:

  1. it offers the gateway's canonical catalog, not a hard-coded list;
  2. editing an app whose stored category predates the catalog does NOT
     silently recategorise it on save;
  3. an unreachable gateway degrades to a usable form instead of blocking
     app creation entirely.
"""
import asyncio

import panels_category_field as pcf


CATALOG = {
    "language": "en",
    "default_category": "productivity",
    "total": 3,
    "groups": [
        {
            "id": "ai",
            "name": "AI",
            "categories": [
                {"id": "ai-media", "name": "AI Media Generation", "icon": "A"},
            ],
        },
        {
            "id": "build",
            "name": "Build",
            "categories": [
                {"id": "developer-tools", "name": "Developer Tools", "icon": "D"},
                {"id": "productivity", "name": "Productivity", "icon": "P"},
            ],
        },
    ],
}


def _patch_catalog(monkeypatch, payload=CATALOG, fail=False):
    async def _get(path):
        if fail:
            raise RuntimeError("gateway unreachable")
        return payload

    monkeypatch.setattr(pcf, "_gw_get", _get)


def _options(monkeypatch, current="", **kw):
    _patch_catalog(monkeypatch, **kw)
    return asyncio.run(pcf.category_options(current))


def test_the_picker_offers_every_catalog_category_grouped(monkeypatch):
    opts, selected = _options(monkeypatch)

    assert [o["value"] for o in opts] == [
        "ai-media",
        "developer-tools",
        "productivity",
    ]
    # ui.Select has no optgroups, so the group rides along in the label —
    # that is what keeps 111 entries scannable.
    assert opts[0]["label"] == "AI - A AI Media Generation"
    # A brand-new app lands on the catalog's own default, never on ""
    # (which would post an empty category).
    assert selected == "productivity"


def test_a_known_category_is_preselected_not_duplicated(monkeypatch):
    opts, selected = _options(monkeypatch, "developer-tools")

    assert selected == "developer-tools"
    assert [o["value"] for o in opts].count("developer-tools") == 1


def test_a_legacy_category_survives_an_edit(monkeypatch):
    """`web-tools` is stored as `tools`, a spelling the catalog does not list.

    If the picker dropped it, opening Edit and pressing Save would quietly
    move a live Marketplace app into a different category. It is kept as an
    explicit, clearly-labelled extra option instead.
    """
    opts, selected = _options(monkeypatch, "tools")

    assert selected == "tools"
    values = [o["value"] for o in opts]
    assert values[0] == "tools", "the current value must lead the list"
    assert values.count("tools") == 1
    # ...and the real catalog is still fully available to move off it.
    assert set(values) >= {"ai-media", "developer-tools", "productivity"}


def test_an_unreachable_gateway_still_renders_a_usable_form(monkeypatch):
    opts, selected = _options(monkeypatch, fail=True)

    assert opts, "the form must never render an empty dropdown"
    assert selected == "productivity"
    assert all(o["value"] and o["label"] for o in opts)


def test_a_legacy_value_survives_even_in_the_fallback(monkeypatch):
    opts, selected = _options(monkeypatch, "tools", fail=True)

    assert selected == "tools"
    assert [o["value"] for o in opts][0] == "tools"


def test_the_field_renders_a_select_bound_to_category(monkeypatch):
    _patch_catalog(monkeypatch)
    node = asyncio.run(pcf.category_field("tools"))

    selects = []

    def walk(n):
        props = getattr(n, "props", {}) or {}
        if getattr(n, "type", None) == "Select":
            selects.append(props)
        for child in props.get("children") or []:
            walk(child)

    walk(node)
    assert len(selects) == 1, "exactly one category dropdown"
    assert selects[0]["param_name"] == "category"
    assert selects[0]["value"] == "tools"
