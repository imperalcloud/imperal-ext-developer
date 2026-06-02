"""Developer Portal — SDL records for the app-secrets domain.

Split from ``models_sdl.py`` to keep each module under the workspace's
300-line god-file ceiling (rule 6). Re-exported from ``models_sdl`` so existing
imports keep working.

Federal I-EXT-RECORD-FIELD-NAMING-SYMMETRIC: field names mirror the EXACT dicts
the secrets handlers build (verified against handlers_secrets.py).
"""
from __future__ import annotations

from typing import Optional

from imperal_sdk import sdl
from pydantic import model_validator


class SecretSaveReceipt(sdl.Entity):
    """Receipt for save_app_secret (kind='secret').

    Mirrors the EXACT dict save_app_secret builds: {ok, app_id, name}.
    """

    ok: Optional[bool] = None
    app_id: Optional[str] = None
    name: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            nm = data.get("name")
            data["id"] = str(nm) if nm not in (None, "") else (data.get("id") or "secret")
            data.setdefault("title", str(nm) if nm not in (None, "") else "Secret")
            data.setdefault("kind", "secret")
        return data


class SecretDeleteReceipt(sdl.Entity):
    """Receipt for delete_app_secret (kind='secret').

    Mirrors the EXACT dict delete_app_secret builds: {ok, was_set}.
    """

    ok: Optional[bool] = None
    was_set: Optional[bool] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            nm = data.get("name")
            data["id"] = str(nm) if nm not in (None, "") else (data.get("id") or "secret")
            data.setdefault("title", str(nm) if nm not in (None, "") else "Secret")
            data.setdefault("kind", "secret")
        return data
