"""Developer Portal — pricing rules: the ONE place a pricing_config is built.

WHY THIS MODULE EXISTS (2026-08-21)

Setting a per-action price through chat reported success and wrote nothing.
Four separate defects, each individually able to produce that outcome:

  1. `save_pricing` never declared a parameter for per-action prices. The
     prices arrived as UNDECLARED extra fields (`price_<tool>`), which the
     panel form supplies but a tool caller cannot see, let alone send. Asked
     to price an action, the only honest thing the caller could produce was
     an empty config.

  2. An empty `tool_prices` still sent `pricing_config: {}`, and the gateway
     faithfully overwrote the row with it. So a chat attempt to ADD a price
     ERASED the prices already configured -- silently, reporting success.

  3. A non-numeric value was coerced to 0 and then dropped (`if price > 0`),
     so a typo removed a price instead of failing.

  4. Success meant "the PUT did not raise". The gateway's own 200 is about
     the request, not about the row: nothing ever read the value back, so
     "Pricing saved" was a statement about network plumbing.

Everything here is PURE -- no gateway, no DB, no ctx. Both the single-app
handler and the bulk handler compute their config with these functions, so
the two paths cannot drift apart. A second implementation for bulk is
exactly how one of them ends up subtly wrong.

MERGE SEMANTICS (the part that matters)

  * a tool ABSENT from the payload keeps its current price;
  * a tool priced 0 is REMOVED (an explicit "make this free");
  * a tool priced >0 is set.

That single rule serves both callers correctly. The panel form submits a
FULL snapshot -- every tool, zeros included -- so a merge reproduces the old
wholesale-replace behaviour exactly. Chat submits a PATCH ("price search at
50"), so a merge protects the prices it did not mention. Under the old
replace-always behaviour the panel was fine and chat was destructive.
"""
from __future__ import annotations

# A single call costing more than this is a fat-finger, not a business model
# (10M tokens ≈ orders of magnitude above any real per-action price). Better a
# loud refusal than a developer's app quietly becoming unusable.
MAX_PRICE = 10_000_000

VALID_MODELS = ("free", "per_action", "subscription")


class PricingError(ValueError):
    """Raised for input that cannot be turned into an honest price.

    Deliberately loud. The bug this module was written to kill was every
    unparseable input becoming a silent 0.
    """


def coerce_price(raw, *, field: str) -> int:
    """Turn a form/tool value into a token price, or refuse to guess.

    Accepts ints and clean numeric strings (`"50"`, `" 50 "`, `"50.0"` when
    integral). Rejects negatives, absurd values, and anything non-numeric --
    the old code turned all three into 0, which reads as "make it free".
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return 0
    if isinstance(raw, bool):                       # True == 1 is never a price
        raise PricingError(f"{field}: expected a number, got a boolean")
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, float):
        if raw != int(raw):
            raise PricingError(f"{field}: prices are whole tokens, got {raw}")
        value = int(raw)
    else:
        text = str(raw).strip().replace("_", "")
        try:
            value = int(text)
        except ValueError:
            try:                                    # "50.0" is a human's 50
                as_float = float(text)
            except ValueError:
                raise PricingError(
                    f"{field}: '{raw}' is not a number. Use whole tokens, e.g. 50."
                ) from None
            # float() happily returns inf/nan for "1e9999" and "nan"; int() then
            # dies with OverflowError/ValueError. Refuse them HERE, in this
            # module's own vocabulary -- a pricing module that answers with a
            # raw numeric traceback is the same unhelpful silence in a new
            # costume. Found by this module's own test, not in production.
            if as_float != as_float or as_float in (float("inf"), float("-inf")):
                raise PricingError(
                    f"{field}: '{raw}' is not a usable number. "
                    f"Use whole tokens, e.g. 50."
                )
            if as_float != int(as_float):
                raise PricingError(f"{field}: prices are whole tokens, got {raw}")
            value = int(as_float)

    if value < 0:
        raise PricingError(f"{field}: a price cannot be negative ({value})")
    if value > MAX_PRICE:
        raise PricingError(
            f"{field}: {value} tokens per call looks like a typo "
            f"(limit {MAX_PRICE:,})"
        )
    return value


def collect_tool_prices(explicit: dict | None, extras: dict | None) -> dict[str, int]:
    """Gather per-tool prices from BOTH shapes into one validated dict.

    `explicit` is the declared `tool_prices` parameter -- what a tool caller
    (and a human asking in words) can actually supply. `extras` carries the
    panel form's `price_<tool>` fields. Supporting both is what lets the fix
    land without breaking the existing form.

    An explicit entry wins over a form field for the same tool: it is the
    more specific statement of intent.
    """
    out: dict[str, int] = {}

    for key, val in (extras or {}).items():
        if not key.startswith("price_"):
            continue
        tool = key[len("price_"):].strip()
        if tool:
            out[tool] = coerce_price(val, field=f"price of '{tool}'")

    for tool, val in (explicit or {}).items():
        name = str(tool).strip()
        if not name:
            continue
        out[name] = coerce_price(val, field=f"price of '{name}'")

    return out


def unknown_tools(prices: dict[str, int], known: list[str] | None) -> list[str]:
    """Names priced but not present in the app's manifest.

    A price on a tool that does not exist can never be charged, so accepting
    it means storing a number that looks set and never applies -- the same
    class of lie this module exists to remove. Returns [] when the manifest
    is unavailable (undeployed app): unverifiable is not the same as wrong.
    """
    if not known:
        return []
    return sorted(n for n in prices if n not in set(known))


def merge_tool_prices(current: dict | None, incoming: dict[str, int]) -> dict[str, int]:
    """Apply incoming prices to current ones: absent keeps, 0 deletes, >0 sets."""
    merged = {}
    for name, val in (current or {}).items():
        try:
            merged[str(name)] = coerce_price(val, field=f"stored price of '{name}'")
        except PricingError:
            continue                                # stored junk must not block an edit
    for name, val in incoming.items():
        if val == 0:
            merged.pop(name, None)
        else:
            merged[name] = val
    return merged


def build_pricing_config(
    current_config: dict | None,
    incoming_prices: dict[str, int],
    monthly_price=None,
) -> dict:
    """Compute the FULL pricing_config to persist.

    The gateway stores this column wholesale, so what is returned here must
    be the complete desired state -- which is exactly why it is built from
    the current value rather than from nothing.

    `monthly_price=None` means "not mentioned" and preserves the stored one;
    0 removes it.
    """
    current = dict(current_config or {})
    config = {k: v for k, v in current.items()
              if k not in ("tool_prices", "monthly_price")}

    merged = merge_tool_prices(current.get("tool_prices"), incoming_prices)
    if merged:
        config["tool_prices"] = merged

    if monthly_price is None:
        stored = current.get("monthly_price")
        if stored:
            try:
                keep = coerce_price(stored, field="stored monthly price")
            except PricingError:
                keep = 0
            if keep > 0:
                config["monthly_price"] = keep
    else:
        monthly = coerce_price(monthly_price, field="monthly price")
        if monthly > 0:
            config["monthly_price"] = monthly

    return config


def normalise_model(model: str | None, current: str | None = None) -> str:
    """Validate the pricing model, defaulting to the app's current one."""
    chosen = (model or current or "free").strip().lower()
    if chosen not in VALID_MODELS:
        raise PricingError(
            f"pricing model '{model}' is not valid — use one of: "
            + ", ".join(VALID_MODELS)
        )
    return chosen


def config_mismatches(expected: dict, actual: dict | None) -> list[str]:
    """Differences between what we asked to store and what came back.

    This is the read-back check that turns "the request did not raise" into
    "the value is in the row". Empty list == the write really landed.
    """
    actual = actual or {}
    problems: list[str] = []

    want_prices = expected.get("tool_prices") or {}
    got_prices_raw = actual.get("tool_prices") or {}
    got_prices = {}
    for name, val in got_prices_raw.items():
        try:
            got_prices[str(name)] = coerce_price(val, field="stored price")
        except PricingError:
            got_prices[str(name)] = val                     # compare as-is; will mismatch

    for name, price in want_prices.items():
        if name not in got_prices:
            problems.append(f"'{name}' was not stored")
        elif got_prices[name] != price:
            problems.append(f"'{name}' stored as {got_prices[name]}, expected {price}")
    for name in got_prices:
        if name not in want_prices:
            problems.append(f"'{name}' unexpectedly still priced")

    want_monthly = expected.get("monthly_price")
    got_monthly = actual.get("monthly_price")
    if want_monthly:
        try:
            got_val = coerce_price(got_monthly, field="stored monthly price")
        except PricingError:
            got_val = None
        if got_val != want_monthly:
            problems.append(
                f"monthly price stored as {got_monthly}, expected {want_monthly}"
            )
    elif got_monthly:
        problems.append("monthly price unexpectedly still set")

    return problems


def describe_prices(prices: dict[str, int], limit: int = 4) -> str:
    """Human summary of what was actually priced ('search 50, fetch 20')."""
    if not prices:
        return "no per-action prices"
    items = sorted(prices.items())
    shown = ", ".join(f"{n} {p} tok" for n, p in items[:limit])
    if len(items) > limit:
        shown += f", +{len(items) - limit} more"
    return shown
