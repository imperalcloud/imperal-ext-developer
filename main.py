"""Developer Portal extension — entry point."""
import sys
import os

_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)

# Purge stale cached modules so hot-reload works correctly
_MODULES = (
    "app",
    "handlers",
    "handlers_deploy",
    "handlers_payout",
    "skeleton",
    "queries",
    "panels",
    "panels_dashboard",
    "panels_overview",
    "panels_pricing",
    "panels_analytics",
    "panels_earnings",
    "panels_deploy",
    "panels_transactions",
    "validation",
    "validation_runtime",
    "validation_report",
)
for _m in [k for k in sys.modules if k in _MODULES]:
    del sys.modules[_m]

from app import ext, chat  # noqa: F401
import handlers            # noqa: F401
import handlers_deploy     # noqa: F401
import handlers_payout     # noqa: F401
import skeleton            # noqa: F401
import panels              # noqa: F401
import panels_dashboard    # noqa: F401
