"""Developer Portal extension — core app, HTTP helpers, hooks."""
import logging
import os
import httpx
from imperal_sdk import Extension
from imperal_sdk.chat import ChatExtension, ActionResult

log = logging.getLogger("developer")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
AUTH_GW = os.environ.get("IMPERAL_GATEWAY_URL", "http://104.224.88.155:8085")
AUTH_SERVICE_TOKEN = os.environ.get("AUTH_SERVICE_TOKEN", "")
REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://66.78.41.10:8098")
REGISTRY_API_KEY = os.environ.get("REGISTRY_API_KEY", "")
EXTENSIONS_DIR = "/opt/extensions"

_PROMPT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "system_prompt.txt")
with open(_PROMPT_FILE, "r", encoding="utf-8") as _f:
    SYSTEM_PROMPT = _f.read().strip()

# ---------------------------------------------------------------------------
# Extension + ChatExtension
# ---------------------------------------------------------------------------
ext = Extension("developer", version="1.4.1",
    display_name='Developer Portal',
    description=(
        'Extension developer hub — publish and manage your own extensions, track deployment status, view earnings analytics, request payouts, and validate manifests against federal SDK rules.'
    ),
    icon="icon.svg",
    actions_explicit=True,
)
chat = ChatExtension(
    ext,
    "tool_developer_chat",
    description="Developer Portal — manage apps, deployments, earnings, and payouts",
    system_prompt=SYSTEM_PROMPT,
)

# ---------------------------------------------------------------------------
# HTTP helpers — Auth Gateway
# ---------------------------------------------------------------------------
_http = None


def _get_http():
    global _http
    if _http is None:
        _http = httpx.AsyncClient(
            base_url=AUTH_GW,
            headers={"X-Service-Token": AUTH_SERVICE_TOKEN},
            timeout=15.0,
        )
    return _http


async def _gw_get(path: str) -> dict:
    r = await _get_http().get(path)
    r.raise_for_status()
    return r.json()


async def _gw_post(path: str, data: dict) -> dict:
    r = await _get_http().post(path, json=data)
    if r.status_code >= 400:
        detail = r.text
        try:
            detail = r.json().get("detail", detail)
        except Exception:
            pass
        raise ValueError(f"API error {r.status_code}: {detail}")
    return r.json()


async def _gw_put(path: str, data: dict) -> dict:
    r = await _get_http().put(path, json=data)
    if r.status_code >= 400:
        detail = r.text
        try:
            detail = r.json().get("detail", detail)
        except Exception:
            pass
        raise ValueError(f"API error {r.status_code}: {detail}")
    return r.json()


async def _gw_delete(path: str, data: dict = None) -> dict:
    r = await _get_http().request("DELETE", path, json=data or {})
    if r.status_code >= 400:
        detail = r.text
        try:
            detail = r.json().get("detail", detail)
        except Exception:
            pass
        raise ValueError(f"API error {r.status_code}: {detail}")
    return r.json()


# ---------------------------------------------------------------------------
# HTTP helpers — Registry
# ---------------------------------------------------------------------------
async def _registry_post(path: str, data: dict) -> dict:
    async with httpx.AsyncClient(base_url=REGISTRY_URL, timeout=15) as c:
        r = await c.post(path, json=data, headers={"x-api-key": REGISTRY_API_KEY})
        r.raise_for_status()
        return r.json()


async def _registry_put(path: str, data: dict) -> dict:
    async with httpx.AsyncClient(base_url=REGISTRY_URL, timeout=15) as c:
        r = await c.put(path, json=data, headers={"x-api-key": REGISTRY_API_KEY})
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# User ID helper
# ---------------------------------------------------------------------------
def _user_id(ctx) -> str:
    return ctx.user.imperal_id if hasattr(ctx, "user") and ctx.user else ""


# ---------------------------------------------------------------------------
# Lifecycle hooks
# ---------------------------------------------------------------------------
@ext.health_check
async def health(ctx) -> dict:
    return {"status": "ok", "version": ext.version}


@ext.on_install
async def on_install(ctx):
    uid = ctx.user.imperal_id if ctx and hasattr(ctx, "user") and ctx.user else "system"
    log.info(f"developer extension installed for user {uid}")


# ---------------------------------------------------------------------------
# Selected app tracking (cross-panel state)
# ---------------------------------------------------------------------------
_selected_app: dict[str, str] = {}


def set_selected_app(uid: str, app_id: str):
    _selected_app[uid] = app_id


def get_selected_app(uid: str) -> str:
    return _selected_app.get(uid, "")
