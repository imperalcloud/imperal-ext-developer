"""Developer Portal — runtime validation via isolated subprocess.

Calls validate_extension_deep.py in a subprocess to safely load
the extension and run SDK V1-V12 + structural checks without
polluting the worker process.
"""
import asyncio
import json
import logging
import os

log = logging.getLogger("developer")

_SCRIPT = "/home/imperal-platform-worker/scripts/validate_extension_deep.py"
_PYTHON = "/home/imperal-platform-worker/venv/bin/python"
_TIMEOUT = 30  # seconds


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
            _PYTHON, _SCRIPT, app_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_TIMEOUT,
        )
    except asyncio.TimeoutError:
        log.warning("Runtime validation timed out for %s", app_dir)
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
