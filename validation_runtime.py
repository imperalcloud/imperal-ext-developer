"""Developer Portal — runtime validation via isolated subprocess.

Calls validate_extension_deep.py in a subprocess to load the extension and
run SDK V1-V12 + structural checks without polluting the worker process.

The subprocess runs code nobody has reviewed yet, so it gets nothing of the
worker's. It runs in its own network, mount, PID, IPC and UTS namespaces: no
network, a private /tmp, an empty /run, /root and /dev/shm (no sockets, no secret
files), and every process it starts dies with it. It runs as nobody with no
capabilities and no new privileges.

Its environment keeps a value only when the value cannot be a secret: a URL
without user, password, query or fragment, a host, port, path, queue or
namespace setting, or a plain flag or number. Every other variable keeps its
name with a placeholder value, so an extension that requires it at import
still loads. Validation results are unchanged (46 installed extensions
compared, 2026-10-23).
"""
import asyncio
import json
import logging
import os
import re
from urllib.parse import urlsplit, urlunsplit

log = logging.getLogger("developer")

_SCRIPT = "/home/imperal-platform-worker/scripts/validate_extension_deep.py"
_PYTHON = "/home/imperal-platform-worker/venv/bin/python"
_TIMEOUT = 30  # seconds
_SANDBOX = [
    "unshare", "--net", "--mount", "--pid", "--ipc", "--uts", "--fork", "--kill-child",
    "--mount-proc", "--", "sh", "-c",
    "mount -t tmpfs -o size=64m tmpfs /tmp && mount -t tmpfs tmpfs /run"
    " && mount -t tmpfs tmpfs /root && mount -t tmpfs tmpfs /dev/shm"
    ' && exec setpriv --reuid=nobody --regid=nogroup --clear-groups --no-new-privs "$@"',
    "validation-sandbox",
]
_PLACEHOLDER = "validation-placeholder"
_SECRET_NAME = re.compile(r"(TOKEN|SECRET|PASS|KEY|CREDENTIAL|HMAC|SALT|PRIVATE)", re.I)
_SETTING_NAME = re.compile(r"_(HOST|PORT|DIR|PATH|QUEUE|NAMESPACE|TENANT|NAME|USER)$")
_PLAIN_VALUE = re.compile(r"(?i)^(true|false|yes|no|on|off|-?\d{1,9}(\.\d+)?)?$")
_STANDARD = {"PATH", "LANG", "LC_ALL", "TZ", "PYTHONUNBUFFERED"}


def _plain_url(value: str) -> str | None:
    """The URL without user, password, query and fragment, or None if it is not a URL."""
    try:
        parts = urlsplit(value)
        if not parts.scheme or not parts.hostname or " " in value:
            return None
        host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
        netloc = host if parts.port is None else f"{host}:{parts.port}"
    except ValueError:
        return None
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _validation_env() -> dict:
    """The worker's environment where only values that cannot be secrets survive."""
    env = {}
    for name, value in os.environ.items():
        if _SECRET_NAME.search(name):
            env[name] = _PLACEHOLDER
        elif name in _STANDARD or _PLAIN_VALUE.match(value):
            env[name] = value
        elif (url := _plain_url(value)) is not None:
            env[name] = url
        elif _SETTING_NAME.search(name):
            env[name] = value
        else:
            env[name] = _PLACEHOLDER
    env.update(PYTHONDONTWRITEBYTECODE="1", HOME="/nonexistent")
    return env


async def run_runtime_validation(app_dir: str) -> dict:
    """Run deep validation in subprocess. Returns parsed JSON result.

    Result shape: {checks: [...], passed: int, total: int, errors: int, warnings: int, ok: bool}
    On failure returns a single failed check with the error.
    """
    if not os.path.isdir(app_dir):
        return _error_result(f"Directory not found: {app_dir}")

    if not os.path.isfile(_SCRIPT):
        return _error_result(f"Validation script not found: {_SCRIPT}")

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *_SANDBOX, _PYTHON, _SCRIPT, app_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_validation_env(), cwd="/",
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_TIMEOUT,
        )
    except asyncio.TimeoutError:
        log.warning("Runtime validation timed out for %s", app_dir)
        if proc is not None:
            proc.kill()      # --kill-child: the sandbox's whole process tree goes with it
            await proc.wait()
        return _error_result(f"Validation timed out after {_TIMEOUT}s")
    except Exception as exc:
        log.error("Runtime validation subprocess failed: %s", exc)
        return _error_result(f"Subprocess error: {exc}")

    if proc.returncode != 0:
        err_text = stderr.decode(errors="replace")[:500]
        # Try parsing stdout anyway — script may have written JSON before crash
        try:
            return json.loads(stdout.decode(errors="replace"))
        except (json.JSONDecodeError, ValueError):
            return _error_result(f"Validator exited with code {proc.returncode}: {err_text}")

    try:
        return json.loads(stdout.decode(errors="replace"))
    except (json.JSONDecodeError, ValueError) as exc:
        log.error("Cannot parse validator output: %s", exc)
        return _error_result(f"Invalid validator output: {exc}")


def _error_result(message: str) -> dict:
    """Return a result with a single failed check."""
    return {
        "checks": [{
            "name": "runtime_error", "phase": "runtime",
            "label": "Runtime validation",
            "passed": False, "detail": message,
            "severity": "critical",
        }],
        "passed": 0, "total": 1, "errors": 1, "warnings": 0, "ok": False,
    }
