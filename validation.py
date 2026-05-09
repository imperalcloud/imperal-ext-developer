"""Developer Portal — extension validation pipeline.

Runs 6 checks on a deployed extension directory:
1. Structure  — main.py exists
2. Manifest   — imperal.json valid with required fields
3. Syntax     — py_compile all .py files
4. File size  — no .py file > 300 lines
5. Security   — no dangerous patterns (eval, exec, os.system, hardcoded secrets)
6. SDK usage  — main.py references imperal_sdk
"""
import json
import os
import py_compile
import re

MAX_LINES = 300

_DANGER_PATTERNS = [
    (r"\beval\s*\(", "eval() call"),
    (r"\bexec\s*\(", "exec() call"),
    (r"\bos\.system\s*\(", "os.system() call"),
    (r"subprocess\.(?:call|run|Popen)\s*\([^)]*shell\s*=\s*True", "subprocess with shell=True"),
    (r"__import__\s*\(", "__import__() call"),
    (r"""(?:password|secret|token|api_key)\s*=\s*["'][^"']{8,}["']""", "hardcoded secret"),
]

# Manifest must have at least one of these as app identifier + version
_MANIFEST_ID_FIELDS = {"name", "app_id"}


def _check_structure(app_dir: str) -> dict:
    main_py = os.path.join(app_dir, "main.py")
    if os.path.isfile(main_py):
        return {"name": "structure", "label": "main.py exists", "passed": True, "detail": "OK"}
    return {"name": "structure", "label": "main.py exists", "passed": False,
            "detail": "main.py not found in extension root"}


def _check_manifest(app_dir: str) -> dict:
    manifest = os.path.join(app_dir, "imperal.json")
    if not os.path.isfile(manifest):
        return {"name": "manifest", "label": "imperal.json valid", "passed": False,
                "detail": "imperal.json not found"}
    try:
        with open(manifest, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"name": "manifest", "label": "imperal.json valid", "passed": False,
                "detail": f"Invalid JSON: {exc}"}
    has_id = bool(_MANIFEST_ID_FIELDS & set(data.keys()))
    has_version = "version" in data
    if not has_id or not has_version:
        missing = []
        if not has_id:
            missing.append("name or app_id")
        if not has_version:
            missing.append("version")
        return {"name": "manifest", "label": "imperal.json valid", "passed": False,
                "detail": f"Missing: {', '.join(missing)}"}
    app_name = data.get("name", data.get("app_id", ""))
    return {"name": "manifest", "label": "imperal.json valid", "passed": True,
            "detail": f"{app_name} v{data['version']}"}


def _check_syntax(app_dir: str) -> dict:
    errors = []
    checked = 0
    for root, _dirs, files in os.walk(app_dir):
        if "__pycache__" in root or ".git" in root:
            continue
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            checked += 1
            try:
                py_compile.compile(fpath, doraise=True)
            except py_compile.PyCompileError as exc:
                rel = os.path.relpath(fpath, app_dir)
                errors.append(f"{rel}: {str(exc).split(chr(10))[0][:120]}")
    if errors:
        return {"name": "syntax", "label": "Python syntax", "passed": False,
                "detail": "; ".join(errors[:5])}
    return {"name": "syntax", "label": "Python syntax", "passed": True,
            "detail": f"{checked} files OK"}


def _check_file_size(app_dir: str) -> dict:
    oversized = []
    for root, _dirs, files in os.walk(app_dir):
        if "__pycache__" in root or ".git" in root:
            continue
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    count = sum(1 for _ in f)
                if count > MAX_LINES:
                    rel = os.path.relpath(fpath, app_dir)
                    oversized.append(f"{rel} ({count}L)")
            except OSError:
                pass
    if oversized:
        return {"name": "file_size", "label": f"No files > {MAX_LINES} lines", "passed": False,
                "detail": ", ".join(oversized[:5])}
    return {"name": "file_size", "label": f"No files > {MAX_LINES} lines", "passed": True,
            "detail": "OK"}


def _check_security(app_dir: str) -> dict:
    findings = []
    for root, _dirs, files in os.walk(app_dir):
        if "__pycache__" in root or ".git" in root:
            continue
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                continue
            rel = os.path.relpath(fpath, app_dir)
            for pattern, label in _DANGER_PATTERNS:
                matches = re.findall(pattern, content)
                if matches:
                    findings.append(f"{rel}: {label} ({len(matches)}x)")
    if findings:
        return {"name": "security", "label": "Security scan", "passed": False,
                "detail": "; ".join(findings[:5])}
    return {"name": "security", "label": "Security scan", "passed": True,
            "detail": "No dangerous patterns found"}


def _check_sdk_usage(app_dir: str) -> dict:
    main_py = os.path.join(app_dir, "main.py")
    if not os.path.isfile(main_py):
        return {"name": "sdk_usage", "label": "Uses Imperal SDK", "passed": False,
                "detail": "main.py not found"}
    try:
        with open(main_py, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as exc:
        return {"name": "sdk_usage", "label": "Uses Imperal SDK", "passed": False,
                "detail": str(exc)}
    if "imperal_sdk" in content or "from app import" in content:
        return {"name": "sdk_usage", "label": "Uses Imperal SDK", "passed": True,
                "detail": "OK"}
    return {"name": "sdk_usage", "label": "Uses Imperal SDK", "passed": False,
            "detail": "main.py does not import imperal_sdk"}


def validate_extension(app_dir: str) -> dict:
    """Run all checks. Returns {checks, passed, total, ok}."""
    checks = [
        _check_structure(app_dir),
        _check_manifest(app_dir),
        _check_syntax(app_dir),
        _check_file_size(app_dir),
        _check_security(app_dir),
        _check_sdk_usage(app_dir),
    ]
    passed = sum(1 for c in checks if c["passed"])
    return {"checks": checks, "passed": passed, "total": len(checks), "ok": passed == len(checks)}


def get_disk_version(app_dir: str) -> dict | None:
    """Read current version from disk: imperal.json + git HEAD."""
    manifest = os.path.join(app_dir, "imperal.json")
    result = {}
    if os.path.isfile(manifest):
        try:
            with open(manifest, "r", encoding="utf-8") as f:
                data = json.load(f)
            result["version"] = data.get("version", "")
            result["name"] = data.get("name", data.get("app_id", ""))
        except Exception:
            pass
    git_head = os.path.join(app_dir, ".git", "refs", "heads", "main")
    if not os.path.isfile(git_head):
        git_head = os.path.join(app_dir, ".git", "refs", "heads", "master")
    if os.path.isfile(git_head):
        try:
            with open(git_head, "r") as f:
                result["commit"] = f.read().strip()[:8]
        except Exception:
            pass
    if not result.get("commit"):
        head_file = os.path.join(app_dir, ".git", "HEAD")
        if os.path.isfile(head_file):
            try:
                with open(head_file, "r") as f:
                    content = f.read().strip()
                if not content.startswith("ref:"):
                    result["commit"] = content[:8]
            except Exception:
                pass
    return result if result else None



def get_extension_tools(app_dir: str) -> list[dict]:
    """Read user-facing tools from imperal.json (skip panels + skeleton)."""
    manifest = os.path.join(app_dir, "imperal.json")
    if not os.path.isfile(manifest):
        return []
    try:
        with open(manifest, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    tools = []
    for t in data.get("tools", []):
        name = t.get("name", "")
        if name.startswith("__panel__") or name.startswith("skeleton_"):
            continue
        tools.append({"name": name, "description": t.get("description", "")[:80]})
    return tools


async def validate_extension_full(app_dir: str) -> dict:
    """Run static + runtime validation. Returns unified report.

    Phase 1: Static (6 filesystem checks — fast, no imports)
    Phase 2: Runtime (subprocess — loads ext, SDK V1-V12, panels, imports)
    Phase 3: Report (merges both, generates LLM-friendly markdown)
    """
    from validation_runtime import run_runtime_validation
    from validation_report import merge_results

    # Phase 1: static
    static = validate_extension(app_dir)

    # Phase 2: runtime (subprocess — isolated)
    runtime = await run_runtime_validation(app_dir)

    # Phase 3: merge + report
    return merge_results(static, runtime)
