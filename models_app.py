"""Developer Portal — SDL records for the app-lifecycle & deploy domain.

Split from ``models_sdl.py`` to keep each module under the workspace's
300-line god-file ceiling (rule 6). Re-exported from ``models_sdl`` so existing
imports keep working.

Federal I-EXT-RECORD-FIELD-NAMING-SYMMETRIC: field names mirror the ACTUAL
runtime dict keys the handler returns (verified against the handlers and
api-contracts/imperal/auth-gateway.json), NOT a synthetic projection.
"""
from __future__ import annotations

from typing import Any, Optional

from imperal_sdk import sdl
from pydantic import model_validator


# ---------------------------------------------------------------------------
# Developer registration (write)
# ---------------------------------------------------------------------------
class DeveloperRegistration(sdl.Entity):
    """Receipt for register_developer (kind='developer').

    Mirrors the raw POST /v1/developer/register response (loosely typed;
    known keys carried as Optional pass-through).
    """

    developer_id: Optional[str] = None
    tier: Optional[str] = None
    is_developer: Optional[Any] = None
    nickname: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            did = data.get("developer_id") or data.get("user_id")
            data["id"] = str(did) if did not in (None, "") else (data.get("id") or "developer")
            data.setdefault("title", data.get("nickname") or "Developer")
            data.setdefault("kind", "developer")
        return data


# ---------------------------------------------------------------------------
# App lifecycle (writes — AppResponse-shaped)
# ---------------------------------------------------------------------------
class AppRecord(sdl.Entity):
    """An extension app (kind='app').

    Mirrors AppResponse (returned verbatim by create_app / update_app_info /
    update_pricing / save_pricing): app_id, developer_id, display_name,
    description, category, icon, git_url, status, reject_reason,
    pricing_model, pricing_config, revenue_split_dev, created_at, updated_at.
    """

    app_id: Optional[str] = None
    developer_id: Optional[str] = None
    display_name: Optional[str] = None
    category: Optional[str] = None
    icon: Optional[str] = None
    git_url: Optional[str] = None
    reject_reason: Optional[str] = None
    pricing_model: Optional[str] = None
    pricing_config: Optional[Any] = None
    revenue_split_dev: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("app_id") or data.get("id") or "app"
            data.setdefault(
                "title", data.get("display_name") or data.get("app_id") or "App")
            data.setdefault("kind", "app")
            data.setdefault("status", data.get("status"))
            data.setdefault("description", data.get("description"))
        return data


class SuspendReceipt(sdl.Entity):
    """Receipt for suspend_app (kind='app').

    Mirrors the raw POST /v1/developer/apps/{app_id}/suspend response (loosely
    typed; the gateway typically echoes app_id/status).
    """

    app_id: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("app_id") or data.get("id") or "app"
            data.setdefault("title", data.get("app_id") or "App")
            data.setdefault("kind", "app")
            data.setdefault("status", data.get("status"))
        return data


class DeleteAppReceipt(sdl.Entity):
    """Receipt for delete_app (kind='app').

    Mirrors the raw DELETE /v1/developer/apps/{app_id} response (loosely typed).
    """

    app_id: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("app_id") or data.get("id") or "app"
            data.setdefault("title", data.get("app_id") or "App")
            data.setdefault("kind", "app")
        return data


class SubmitReceipt(sdl.Entity):
    """Receipt for submit_for_review (kind='appsubmit').

    Mirrors AppSubmitResponse (returned verbatim): status, checks.
    """

    checks: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("app_id") or data.get("id") or "submission"
            data.setdefault("title", data.get("app_id") or "Submission")
            data.setdefault("kind", "appsubmit")
            data.setdefault("status", data.get("status"))
        return data


# ---------------------------------------------------------------------------
# Deploy (write — explicit handler-built dict)
# ---------------------------------------------------------------------------
class DeployReceipt(sdl.Entity):
    """Receipt for deploy_app (kind='deploy').

    Mirrors the EXACT dict deploy_app builds: app_id, commit, status,
    validation, tools_synced, panels_synced, icon_synced, manifest_synced,
    migrations_applied.
    """

    app_id: Optional[str] = None
    commit: Optional[str] = None
    validation: Optional[str] = None
    tools_synced: Optional[int] = None
    panels_synced: Optional[bool] = None
    icon_synced: Optional[bool] = None
    manifest_synced: Optional[bool] = None
    migrations_applied: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("app_id") or data.get("id") or "deploy"
            data.setdefault("title", data.get("app_id") or "Deploy")
            data.setdefault("kind", "deploy")
            data.setdefault("status", data.get("status"))
        return data


# ---------------------------------------------------------------------------
# Smoke-run (read — explicit handler-built dict)
# ---------------------------------------------------------------------------
class SmokeReceipt(sdl.Entity):
    """Receipt for smoke_ir (kind='smoke').

    Mirrors the EXACT dict smoke_ir builds: ok, result, trace.
    """

    ok: bool = False
    result: Optional[Any] = None
    trace: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("id") or "smoke"
            data.setdefault("title", "Smoke run")
            data.setdefault("kind", "smoke")
        return data


# ---------------------------------------------------------------------------
# Skeleton timer (write — handler-built dict)
# ---------------------------------------------------------------------------
class SkeletonConfigReceipt(sdl.Entity):
    """Receipt for save_skeleton_ttl (kind='extension').

    Handler-built dict: app_id, updated, sections (the section_name/ttl_override
    pairs applied).
    """

    app_id: Optional[str] = None
    updated: Optional[bool] = None
    sections: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("app_id") or data.get("id") or "app"
            data.setdefault("title", data.get("app_id") or "Skeleton config")
            data.setdefault("kind", "extension")
        return data
