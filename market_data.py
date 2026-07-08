__version__ = "1.2.3"
# Copyright 2026 Gregory Howard

import time
import requests

from config_loader import load_merged_config

_cfg = load_merged_config()
STRIKE_STEP = int(_cfg.get("STRIKE_STEP", 5))


# ============================================================
# NEW IMPLEMENTATION (ACTIVE CODE)
# ============================================================

# UPDATED: add allow_fallback_polling to prevent startup hangs when historical bars are unavailable
def get_historical_minute_bars(client, minutes_needed, symbol="SPX", allow_fallback_polling=True):  #2
    """
    Fetch historical 1-minute SPX bars.

    If the broker supports historical queries, use them.
    If not, fallback to repeated polling (same behavior as old rebuild).
    """

    # NEW: Attempt historical endpoint using correct request method
    try:
        # NEW: explicit URL logging for diagnostics
        hist_url = f"{client.base_url}/marketdata/barcharts/{symbol}?interval=1&barsback={minutes_needed}"  #2
        print(f"[market_data] Historical request: {hist_url}")

        r = client._req(
            method=requests.get,
            # OLD (COMMENTED OUT): url=f"{client.base_url}/marketdata/barcharts/{symbol}?interval=1&barsback={minutes_needed}"  #2
            url=hist_url
        )
        if r and "Bars" in r:
            bars = r["Bars"]
            prices = [float(b["Close"]) for b in bars][-minutes_needed:]
            # OLD (COMMENTED OUT): required exact match
            # if len(prices) == minutes_needed:
            #     return prices
            # UPDATED: accept partial history; caller enforces minimum depth
            if len(prices) > 0:
                # NEW: success diagnostic
                print(f"[market_data] Historical fetch OK for {symbol}: got {len(prices)} bars")
                return prices
            else:
                # NEW: explicit empty-close diagnostic
                print(f"[market_data] Historical fetch returned Bars but no usable closes for {symbol}")
        else:
            # NEW: explicit diagnostic when endpoint returns no Bars
            try:
                keys = list(r.keys()) if isinstance(r, dict) else str(type(r))
            except Exception:
                keys = "unknown"
            print(f"[market_data] Historical fetch returned no Bars for {symbol}; response keys/type: {keys}")

            # NEW: short payload preview for debugging
            try:
                preview = str(r)
                if len(preview) > 400:
                    preview = preview[:400] + "...(truncated)"
            except Exception:
                preview = "<unprintable>"
            print(f"[market_data] Historical response preview for {symbol}: {preview}")
    except Exception as e:
        print(f"[market_data] Historical bar fetch failed for {symbol}: {e}")  #2

    # NEW: optional fail-fast path (used by bootstrap to avoid long blocking loop)
    if not allow_fallback_polling:
        # NEW: explicit fail-fast diagnostic
        print(f"[market_data] historical bars unavailable for {symbol}; fallback polling disabled")
        return []

    # OLD CODE (COMMENTED OUT)
    # try:
    #     r = client._req(
    #         method=client._headers,  # WRONG: this is a method, not a request function
    #         url=f"{client.base_url}/marketdata/barcharts/SPX?interval=1&barsback={minutes_needed}"
    #     )
    #     if r and "Bars" in r:
    #         bars = r["Bars"]
    #         prices = [float(b["Close"]) for b in bars][-minutes_needed:]
    #         if len(prices) == minutes_needed:
    #             return prices
    # except:
    #     pass

    # Fallback: repeated polling (same as old get_minute_prices_for_rebuild)
    prices = []

    while len(prices) < minutes_needed:
        try:  #1
            data = client.get_quotes([symbol])  #2
            if data and "Quotes" in data and data["Quotes"]:  #2
                prices.append(float(data["Quotes"][0]["Last"]))  #2
            else:  #1
                print(f"[market_data] No Quotes for {symbol} during fallback polling")  #1
        except Exception as e:  #1
            print(f"[market_data] Fallback polling error for {symbol}: {e}")  #1
        time.sleep(60)

    return prices[-minutes_needed:]


# ============================================================
# COMPATIBILITY WRAPPERS EXPECTED BY main.py
# ============================================================

# UPDATED: add allow_fallback_polling knob (default False for rebuild bootstrap)
def get_minute_prices_for_rebuild(client, expiry, symbol="SPX", barsback=60, allow_fallback_polling=False):  #2
    """
    Compatibility wrapper for rebuild prices.

    UPDATED: barsback is configurable so EMA bootstrap can request
    EMA_REBUILD_DEPTH instead of hardcoded 60.
    """
    # expiry is currently unused in this wrapper but kept for API compatibility
    # OLD (COMMENTED OUT): return get_historical_minute_bars(client, 60, symbol=symbol)  #2
    return get_historical_minute_bars(
        client,
        int(barsback),
        symbol=symbol,
        allow_fallback_polling=allow_fallback_polling
    )  #2


def get_atm_surface(client, expiry, spx_price):
    """
    Production ATM surface provider.

    Rounds spx_price to the nearest configured STRIKE_STEP to produce the
    correct at-the-money strike for listed SPXW options (default 5-point intervals).

    Returns: {"atm": int}

    OLD (COMMENTED OUT):
    # atm = int(round(spx_price))   — incorrect: rounds to nearest int, not strike step
    # e.g. SPX=5502.30 → atm=5502, but no SPXW option exists at strike 5502
    """
    atm = int(round(spx_price / STRIKE_STEP) * STRIKE_STEP)
    return {"atm": atm}


# ============================================================
# Option Quote + Vertical Spread Quote Helpers
# ============================================================

def get_option_quote(client, expiry, strike, right):
    """
    Fetch bid/ask/mid for a single option.

    right: "C" or "P"
    Returns dict {"bid": float, "ask": float, "mid": float} or None on failure.

    Validates:
    - ask > 0           (non-zero market — zero ask means no offer / invalid)
    - ask >= bid        (non-inverted quote)
    - mid > 0
    """
    from order_builder import format_option_symbol

    symbol = format_option_symbol(expiry, strike, right)

    try:
        r = client.get_quotes([symbol])
        if not r or "Quotes" not in r or len(r["Quotes"]) < 1:
            print(f"[market_data] No quote returned for {symbol}")
            return None

        q = r["Quotes"][0]
        bid = float(q.get("Bid", 0) or 0)
        ask = float(q.get("Ask", 0) or 0)

        if ask <= 0:
            print(f"[market_data] Invalid ask=0 for {symbol} — skipping")
            return None

        if ask < bid:
            print(f"[market_data] Inverted quote for {symbol}: bid={bid} ask={ask} — skipping")
            return None

        mid = round((bid + ask) / 2, 4)

        if mid <= 0:
            print(f"[market_data] Non-positive mid={mid} for {symbol} — skipping")
            return None

        return {"bid": bid, "ask": ask, "mid": mid}

    except Exception as e:
        print(f"[market_data] get_option_quote error ({symbol}): {e}")
        return None


def get_spread_quote(client, expiry, long_strike, short_strike, right):
    """
    Fetch bid/ask/mid for a 2-leg debit vertical spread.

    For BUY long / SELL short:
      spread_bid = long_bid - short_ask
      spread_ask = long_ask - short_bid
      spread_mid = (spread_bid + spread_ask) / 2

    Validates:
    - Both legs have non-zero ask/bid
    - spread_ask > 0        (spread has positive market value)
    - spread_ask >= spread_bid  (non-inverted spread)
    """
    from order_builder import format_option_symbol

    long_sym = format_option_symbol(expiry, long_strike, right)
    short_sym = format_option_symbol(expiry, short_strike, right)

    try:
        r = client.get_quotes([long_sym, short_sym])
        if not r or "Quotes" not in r or len(r["Quotes"]) < 2:
            print(f"[market_data] Incomplete quotes for spread {long_sym}/{short_sym}")
            return None

        long_q = next((q for q in r["Quotes"] if q.get("Symbol", "") == long_sym), None)
        short_q = next((q for q in r["Quotes"] if q.get("Symbol", "") == short_sym), None)

        if not long_q or not short_q:
            print(f"[market_data] Could not match both legs in spread quote response")
            return None

        long_bid = float(long_q.get("Bid", 0) or 0)
        long_ask = float(long_q.get("Ask", 0) or 0)
        short_bid = float(short_q.get("Bid", 0) or 0)
        short_ask = float(short_q.get("Ask", 0) or 0)

        if long_ask <= 0 or short_bid <= 0:
            print(f"[market_data] Zero ask/bid in spread legs: long_ask={long_ask} short_bid={short_bid} — skipping")
            return None

        spread_bid = round(long_bid - short_ask, 4)
        spread_ask = round(long_ask - short_bid, 4)

        if spread_ask <= 0:
            print(f"[market_data] Non-positive spread_ask={spread_ask} for {long_sym}/{short_sym} — skipping")
            return None

        if spread_ask < spread_bid:
            print(f"[market_data] Inverted spread: bid={spread_bid} ask={spread_ask} for {long_sym}/{short_sym} — skipping")
            return None

        spread_mid = round((spread_bid + spread_ask) / 2, 4)

        return {"bid": spread_bid, "ask": spread_ask, "mid": spread_mid}

    except Exception as e:
        print(f"[market_data] get_spread_quote error ({long_sym}/{short_sym}): {e}")
        return None