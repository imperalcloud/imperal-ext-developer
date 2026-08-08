"""Developer Portal extension — entry point."""
import sys
import os

_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)

# Purge every stale cached module belonging to THIS extension on each load.
# Matching by file location (not name/prefix) is truly self-maintaining: any
# past or future top-level module — handlers_secrets, deploy_ir, smoke_ir, or
# whatever comes next — is caught automatically, because the platform's
# double-load validation pass re-imports main.py in the SAME process. A
# prefix/name allowlist bit us twice for the same underlying reason:
#   - handlers_secrets was missing from an earlier hand-maintained list,
#     leaving the secrets handlers bound to a stale ChatExtension (manifest
#     drift on save_app_secret / delete_app_secret).
#   - deploy_ir / smoke_ir have no handlers_/panels_ prefix, so they were
#     never covered by the wildcard match either — same drift class, this
#     time reported by the validator as "in imperal.json but not registered
#     in code" even though both tools are real, working @chat.function's.
# `app` itself is included explicitly since it defines `ext`/`chat` fresh.
# `main` itself is explicitly EXCLUDED — it is the currently-executing module;
# deleting its own sys.modules entry mid-exec is an unnecessary risk this
# purge doesn't need to take (nothing re-imports `main` from within main.py).
for _name, _mod in list(sys.modules.items()):
    if _name == "main":
        continue
    _mod_file = getattr(_mod, "__file__", None)
    if _name == "app" or (_mod_file and os.path.dirname(os.path.abspath(_mod_file)) == _dir):
        del sys.modules[_name]

from app import ext, chat  # noqa: F401
import handlers            # noqa: F401
import handlers_bulk       # noqa: F401  Bulk app ops: deploy/suspend/submit many apps in one call
import handlers_deploy     # noqa: F401
import handlers_payout     # noqa: F401
import handlers_secrets    # noqa: F401  EXT-SECRETS-V1 Secrets tab handlers
import handlers_submit     # noqa: F401  submit_for_review (split from handlers_deploy)
import handlers_skeleton   # noqa: F401  save_skeleton_ttl (split from handlers)
import deploy_ir           # noqa: F401  deploy_ir @chat.function (P1.2)
import smoke_ir            # noqa: F401  smoke_ir @chat.function (P2)
import skeleton            # noqa: F401
import panels              # noqa: F401
import panels_dashboard    # noqa: F401
