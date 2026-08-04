"""Developer Portal — git helpers (split from handlers_deploy.py)."""
import asyncio
import os
import re
import shutil
import logging

PIPE = asyncio.subprocess.PIPE
log = logging.getLogger("developer")

# I-FIRSTPARTY-ADMIN-ONLY-CLAIM (2026-05-09): system-tier first-party
# extensions Admin can re-deploy through the canonical Dev Portal flow.
# Sharelock is intentionally NOT here — it's an enterprise/agency-tier
# product with its own deploy lifecycle. When the deployed dir at
# /opt/extensions/<app_id>/ exists without `.git/` (legacy hand-deploy),
# admin re-deploy backs up the dir and clones from git_url.
FIRSTPARTY_APP_IDS = {"admin", "automations", "billing", "developer", "hello-world"}
FIRSTPARTY_BACKUP_DIR = "/opt/backups/extensions"


def _normalise_git_url(url: str) -> str:
    """Canonical ``host/owner/repo`` for OWNERSHIP COMPARISON only.

    The canonical publish flow is: developer pushes to GitHub, then deploys
    from the Dev Portal. The SAME GitHub repo is legitimately addressed as
    ``git@github.com:owner/repo.git`` (what a local clone's origin says) and
    ``https://github.com/owner/repo.git`` (what the Portal form submits).
    Comparing those as RAW STRINGS made the squat guard refuse a developer's
    OWN repo -- so this collapses scheme, embedded credentials, scp-vs-URL
    shape, an optional port, a ``.git`` suffix, a trailing slash and case.

    The squat defence is UNCHANGED in substance: host, owner and repo must
    all still match, so a different repo, a different owner or a lookalike
    host still compares as different. Never raises -- an unparseable URL just
    normalises to itself (lowercased), which keeps the old refuse behaviour.
    """
    if not url:
        return ""
    s = url.strip()
    s = re.sub(r"^(https?|ssh|git)://", "", s, flags=re.I)
    if "@" in s.split("/")[0]:
        s = re.sub(r"^[^/@]+@", "", s, count=1)
    s = re.sub(r"^([^/:]+):(?!\d)", r"\1/", s, count=1)
    s = re.sub(r"^([^/:]+):\d+/", r"\1/", s, count=1)
    s = s.rstrip("/")
    if s.lower().endswith(".git"):
        s = s[:-4]
    return s.lower()


async def _git_remote_url(app_dir: str) -> str | None:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", app_dir, "remote", "get-url", "origin",
        stdout=PIPE, stderr=PIPE,
    )
    out, _ = await proc.communicate()
    return out.decode().strip() if proc.returncode == 0 else None


async def _git_pull_or_clone(
    app_dir: str,
    git_url: str,
    *,
    caller_role: str = "developer",
    app_id: str = "",
) -> tuple[str, str]:
    """Clone or pull with smart directory handling.

    `caller_role` + `app_id` thread `I-FIRSTPARTY-ADMIN-ONLY-CLAIM`
    through the squat-refuse branch: when an admin re-deploys a system
    first-party extension whose dir exists without a `.git/` (legacy
    hand-deploy shape), back up + clone instead of refusing.
    """
    # Pin git's safe.directory for this extension dir so files written
    # by rsync/restore from a different uid don't trip the dubious-
    # ownership check. Idempotent — git silently dedups.
    try:
        _safe_proc = await asyncio.create_subprocess_exec(
            "git", "config", "--global", "--add", "safe.directory", app_dir,
            stdout=PIPE, stderr=PIPE,
        )
        await _safe_proc.communicate()
    except Exception as exc:
        log.warning("safe.directory pin failed for %s: %s", app_dir, exc)

    git_dir = os.path.join(app_dir, ".git")

    if os.path.isdir(git_dir):
        # Squatting defence: if the existing repo's origin does not match
        # the caller's declared git_url, refuse. Remote-URL equality is
        # our ownership proof for the .git-exists branch -- compared on the
        # NORMALISED form (host/owner/repo), so the same GitHub repo reached
        # over ssh and over https is correctly seen as the same repo, while
        # a different repo/owner/host still refuses.
        current_remote = await _git_remote_url(app_dir)
        if current_remote and _normalise_git_url(current_remote) != _normalise_git_url(git_url):
            return ("squatting_refused",
                    f"/opt/extensions path already owned by a different git remote "
                    f"({current_remote}); refusing to overwrite with {git_url}")

        # task #75: fetch+reset replaces `git pull --ff-only`. Upstream is
        # source of truth — deploy MUST succeed regardless of local worktree
        # state. fetch + reset --hard is idempotent and never fails on dirty.
        proc_fetch = await asyncio.create_subprocess_exec(
            "git", "-C", app_dir, "fetch", "origin",
            stdout=PIPE, stderr=PIPE,
        )
        _, fetch_err = await proc_fetch.communicate()
        if proc_fetch.returncode != 0:
            return ("pull_failed", fetch_err.decode()[:300])

        # Resolve default branch — prefer symbolic-ref; fallback to main/master.
        proc_def = await asyncio.create_subprocess_exec(
            "git", "-C", app_dir, "symbolic-ref", "--short", "refs/remotes/origin/HEAD",
            stdout=PIPE, stderr=PIPE,
        )
        def_out, _ = await proc_def.communicate()
        default_ref = def_out.decode().strip() or "origin/main"
        if not default_ref.startswith("origin/"):
            default_ref = "origin/" + default_ref.split("/")[-1]

        # Hard-reset to upstream
        proc_reset = await asyncio.create_subprocess_exec(
            "git", "-C", app_dir, "reset", "--hard", default_ref,
            stdout=PIPE, stderr=PIPE,
        )
        _, reset_err = await proc_reset.communicate()
        if proc_reset.returncode != 0:
            for fallback in ("origin/main", "origin/master"):
                if fallback == default_ref:
                    continue
                proc_fb = await asyncio.create_subprocess_exec(
                    "git", "-C", app_dir, "reset", "--hard", fallback,
                    stdout=PIPE, stderr=PIPE,
                )
                _, fb_err = await proc_fb.communicate()
                if proc_fb.returncode == 0:
                    return ("pulled", "")
            return ("pull_failed", reset_err.decode()[:300])

        # Optional tidy: drop untracked files from previous clone.
        proc_clean = await asyncio.create_subprocess_exec(
            "git", "-C", app_dir, "clean", "-fd",
            stdout=PIPE, stderr=PIPE,
        )
        await proc_clean.communicate()
        return ("pulled", "")

    if os.path.isdir(app_dir):
        # Squatting defence: path exists but has no `.git` subdir.
        # I-FIRSTPARTY-ADMIN-ONLY-CLAIM: when re-deploying a system first-
        # party extension, back up the legacy hand-deployed copy and
        # continue to clone. We don't double-check caller_role because
        # deploy_app's upstream _gw_get already enforces row ownership.
        if app_id in FIRSTPARTY_APP_IDS:
            import time as _time
            import tarfile as _tarfile
            os.makedirs(FIRSTPARTY_BACKUP_DIR, exist_ok=True)
            ts = int(_time.time())
            backup_path = os.path.join(FIRSTPARTY_BACKUP_DIR, f"{app_id}.{ts}.tar.gz")
            try:
                with _tarfile.open(backup_path, "w:gz") as tf:
                    tf.add(app_dir, arcname=os.path.basename(app_dir))
                shutil.rmtree(app_dir)
                log.info(
                    "I-FIRSTPARTY-ADMIN-ONLY-CLAIM: backed up %s to %s before clone",
                    app_dir, backup_path,
                )
            except (OSError, _tarfile.TarError) as exc:
                return ("backup_failed",
                        f"Failed to back up legacy {app_dir} -> {backup_path}: {exc}")
        else:
            return ("squatting_refused",
                    f"/opt/extensions/{os.path.basename(app_dir)} is already occupied by "
                    f"a non-developer-portal extension (no .git dir); refusing to deploy. "
                    f"Contact platform admin if you believe this is your app.")

    proc = await asyncio.create_subprocess_exec(
        "git", "clone", "--depth", "1", git_url, app_dir,
        stdout=PIPE, stderr=PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        return ("clone_failed", stderr.decode()[:300])
    return ("cloned", "")
