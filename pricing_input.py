"""Strict boundary coercion for structured Developer Portal pricing inputs."""
from __future__ import annotations

import json
from typing import Annotated, Any, TypeVar

from pydantic import BeforeValidator

T = TypeVar("T", dict, list)


def _json_object(value: Any) -> Any:
    return decode_json_container(value, dict, field="tool_prices")


def _pricing_config(value: Any) -> Any:
    return decode_json_container(value, dict, field="pricing_config")


def _app_ids(value: Any) -> Any:
    return decode_json_container(value, list, field="app_ids")


JsonObject = Annotated[dict, BeforeValidator(_json_object)]
PricingConfig = Annotated[dict, BeforeValidator(_pricing_config)]
AppIds = Annotated[list[str], BeforeValidator(_app_ids)]


def decode_json_container(value: Any, expected: type[T], *, field: str) -> T | Any:
    """Accept an already-typed value or its JSON transport representation.

    LLM/function-call transports occasionally preserve nested JSON as a string.
    Decode only JSON objects/arrays required by an explicitly typed parameter;
    ordinary strings remain invalid instead of being silently reinterpreted.
    """
    if not isinstance(value, str):
        return value
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} must be a JSON {expected.__name__}") from exc
    if not isinstance(decoded, expected):
        raise ValueError(f"{field} must be a JSON {expected.__name__}")
    return decoded
