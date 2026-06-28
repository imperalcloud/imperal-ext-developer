"""Developer Portal extension — entry point."""
import sys
import os

_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)

# Purge every stale cached module on each load. The hardcoded enumeration this
# replaces was missing handlers_secrets, which caused the Dev Portal's double-
# load validation pass to leave the secrets handlers bound to a stale chat
# extension — manifest drift on save_app_secret / delete_app_secret. Wildcard
# match keeps the list self-maintaining as new modules are added.
for _m in [k for k in list(sys.modules)
           if k == "app"
           or k.startswith(("handlers_", "panels_", "validation", "models"))
           or k in ("handlers", "panels", "skeleton", "queries")]:
    del sys.modules[_m]

from app import ext, chat  # noqa: F401
import handlers            # noqa: F401
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
