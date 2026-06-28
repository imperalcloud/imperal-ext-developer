from skeleton_ttl import build_override_sections, human_interval


def test_numeric_override():
    assert build_override_sections({"ttl_mail_inbox_summary": "300"}) == [
        {"section_name": "mail_inbox_summary", "ttl_override": 300}
    ]


def test_default_resets_to_none():
    assert build_override_sections({"ttl_portfolio": "default"}) == [
        {"section_name": "portfolio", "ttl_override": None}
    ]


def test_ignores_non_ttl_fields():
    out = build_override_sections({"price_foo": "5", "app_id": "x", "ttl_y": "60"})
    assert out == [{"section_name": "y", "ttl_override": 60}]


def test_skips_invalid_number():
    assert build_override_sections({"ttl_z": "abc"}) == []


def test_human_interval():
    assert human_interval(30) == "30s"
    assert human_interval(300) == "5m"
    assert human_interval(3600) == "1h"
    assert human_interval(86400) == "1d"
