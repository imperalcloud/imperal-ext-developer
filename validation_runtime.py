"""Developer Portal — runtime validation via isolated subprocess.

Calls validate_extension_deep.py in a subprocess to load the extension and
run SDK V1-V12 + structural checks without polluting the worker process.

The subprocess runs code nobody has reviewed yet, so it gets nothing of the
worker's: user nobody (no root, no new privileges), no network, and the
worker's environment with every secret replaced by a placeholder. Non-secret
settings (backend URLs, flags) stay, so an extension that reads them at import
validates exactly as before (checked on 46 installed extensions, 2026-10-23).
"""
import asyncio
import json
import logging
import os
import re

log = logging.getLogger("developer")

_SCRIPT = "/home/imperal-platform-worker/scripts/validate_extension_deep.py"
_PYTHON = "/home/imperal-platform-worker/venv/bin/python"
_TIMEOUT = 30  # seconds
_SANDBOX = ["unshare", "--net", "--", "setpriv", "--reuid=nobody", "--regid=nogroup",
            "--clear-groups", "--no-new-privs"]
_SECRET_NAME = re.compile(r"(TOKEN|SECRET|PASS|KEY|CREDENTIAL|HMAC|SALT)", re.I)
_PLACEHOLDER = "validation-placeholder"


def _validation_env() -> dict:
    """The worker's environment with every secret value replaced: by name (token, key,
    password ...) and credentials inside URLs (scheme://user:pass@host -> placeholders)."""
    env = {}
    for name, value in os.environ.items():
        if _SECRET_NAME.search(name):
            env[name] = _PLACEHOLDER
            continue
        scheme, sep, rest = value.partition("://")
        if sep and "@" in rest.split("/", 1)[0]:
            env[name] = f"{scheme}://validation:placeholder@{rest.split('@', 1)[1]}"
            continue
        env[name] = value
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

    try:
        proc = await asyncio.create_subprocess_exec(
            *_SANDBOX, _PYTHON, _SCRIPT, app_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_validation_env(), cwd="/tmp",
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_TIMEOUT,
        )
    except asyncio.TimeoutError:
        log.warning("Runtime validation timed out for %s", app_dir)
        proc.kill()
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
