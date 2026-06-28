"""Pure helpers for the Developer-Portal Skeleton timer editor (no app/SDK
imports — unit-testable in isolation). The cadence is a global, developer-owned
value: ttl_override (UI) over the manifest ttl default."""

# Fixed presets (min 30s — abuse guard). "default" sentinel clears the override.
TTL_OPTIONS = [
    {"label": "Default (manifest)", "value": "default"},
    {"label": "Every 30 seconds", "value": "30"},
    {"label": "Every minute", "value": "60"},
    {"label": "Every 5 minutes", "value": "300"},
    {"label": "Every 10 minutes", "value": "600"},
    {"label": "Every hour", "value": "3600"},
    {"label": "Once a day", "value": "86400"},
]


def human_interval(seconds) -> str:
    """Seconds -> compact label: 30s / 5m / 1h / 1d."""
    try:
        s = int(seconds)
    except (ValueError, TypeError):
        return "—"
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


def build_override_sections(extra: dict) -> list:
    """Map submitted form fields ``ttl_<section>`` -> settings-PUT sections.

    ``"default"``/empty -> ``ttl_override=None`` (reset to manifest default);
    a numeric string -> ``ttl_override=int``. Non-``ttl_`` fields and
    unparseable numbers are ignored.
    """
    sections = []
    for key, val in (extra or {}).items():
        if not key.startswith("ttl_"):
            continue
        section_name = key[len("ttl_"):]
        if not section_name:
            continue
        if val in ("default", "", None):
            sections.append({"section_name": section_name, "ttl_override": None})
            continue
        try:
            sections.append({"section_name": section_name, "ttl_override": int(val)})
        except (ValueError, TypeError):
            continue
    return sections
