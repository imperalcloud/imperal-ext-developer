"""Deploy validation runs unreviewed extension code: as nobody, without network, and with
every worker secret replaced by a placeholder (2026-10-23 isolation audit: it ran as root
with the kernel's full environment, before any review)."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import validation_runtime as vr


def test_secrets_are_replaced_and_settings_kept(monkeypatch):
    monkeypatch.setattr(os, "environ", {
        "AUTH_SERVICE_TOKEN": "real-token",
        "ANTHROPIC_API_KEY": "sk-real",
        "REDIS_PASS": "pw",
        "IMPERAL_CALL_TOKEN_HMAC_SECRET": "h",
        "DATABASE_URL": "mysql+aiomysql://imperal_auth:pw@db.internal:3306/imperal_auth",
        "REDIS_URL": "redis://kernel:pw@10.88.0.1:6379/0",
        "NOTES_API_URL": "http://10.88.0.5:8080",
        "PATH": "/usr/bin",
    })
    env = vr._validation_env()
    for name in ("AUTH_SERVICE_TOKEN", "ANTHROPIC_API_KEY", "REDIS_PASS", "IMPERAL_CALL_TOKEN_HMAC_SECRET"):
        assert env[name] == vr._PLACEHOLDER
    assert env["DATABASE_URL"] == "mysql+aiomysql://validation:placeholder@db.internal:3306/imperal_auth"
    assert env["REDIS_URL"] == "redis://validation:placeholder@10.88.0.1:6379/0"
    assert env["NOTES_API_URL"] == "http://10.88.0.5:8080"
    assert env["PATH"] == "/usr/bin"
    assert not any(v in str(env.values()) for v in ("real-token", "sk-real", ":pw@"))


def test_the_validator_runs_as_nobody_without_network(monkeypatch, tmp_path):
    seen = {}

    class _Proc:
        returncode = 0

        async def communicate(self):
            return json.dumps({"checks": [], "ok": True}).encode(), b""

    async def fake_exec(*cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return _Proc()

    monkeypatch.setattr(vr, "_SCRIPT", __file__)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    out = asyncio.run(vr.run_runtime_validation(str(tmp_path)))
    assert out["ok"] is True
    cmd = list(seen["cmd"])
    assert cmd[:3] == ["unshare", "--net", "--"]
    assert "--reuid=nobody" in cmd and "--no-new-privs" in cmd
    assert cmd[-3:] == [vr._PYTHON, __file__, str(tmp_path)]
    assert seen["kw"]["env"]["HOME"] == "/nonexistent"
