"""Resolve the callable pricing surface for a deployed extension."""
from __future__ import annotations

import logging
import os

from app import EXTENSIONS_DIR

log = logging.getLogger("developer.pricing_catalog")


def known_tools(app_id: str) -> list[str]:
    """Use the loaded callable surface; fall back to the deployed manifest.

    The loader is authoritative after deploy. The manifest remains a resilient
    fallback when the loader cannot run, such as an undeployed or invalid app.
    """
    try:
        from imperal_kernel.core.loader import ExtensionLoader
        from imperal_sdk.catalog import callable_functions

        ext = ExtensionLoader(EXTENSIONS_DIR).load(app_id)
        if ext is not None:
            names = [entry.get("name", "") for entry in callable_functions(ext)]
            names = [name for name in names if name and not name.startswith("__")]
            if names:
                return names
    except Exception as exc:  # noqa: BLE001
        log.debug("live tool list unavailable for %s: %s", app_id, exc)

    try:
        from validation import get_extension_tools

        tools = get_extension_tools(os.path.join(EXTENSIONS_DIR, app_id))
        return [tool["name"] for tool in tools if tool.get("name")]
    except Exception as exc:  # noqa: BLE001
        log.debug("manifest tool list unavailable for %s: %s", app_id, exc)
        return []
