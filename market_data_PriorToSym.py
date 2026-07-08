__version__ = "1.2.0"
# Copyright 2026 Gregory Howard

import time
import requests

from config_loader import load_merged_config

_cfg = load_merged_config()
STRIKE_STEP = int(_cfg.get("STRIKE_STEP", 5))


# ============================================================
# NEW IMPLEMENTATION (ACTIVE CODE)
# ============================================================

def get_historical_minute_bars(client, minutes_needed):
    """
    Fetch historical 1-minute SPX bars.

    If the broker supports historical queries, use them.
    If not, fallback to repeated polling (same behavior as old rebuild).
    """

    # NEW: Attempt historical endpoint using correct request method
    try:
        r = client._req(
            method=requests.get,
            url=f"{client.base_url}/marketdata/barcharts/SPX?interval=1&barsback={minutes_needed}"
        )
        if r and "Bars" in r:
            bars = r["Bars"]
            prices = [float(b["Close"]) for b in bars][-minutes_needed:]
            if len(prices) == minutes_needed:
                return prices
    except Exception as e:
        print(f"[market_data] Historical bar fetch failed: {e}")

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
        data = client.get_spx_price()
        if data:
            prices.append(float(data["Quotes"][0]["Last"]))
        time.sleep(60)

    return prices[-minutes_needed:]


# ============================================================
# COMPATIBILITY WRAPPERS EXPECTED BY main.py
# ============================================================

def get_minute_prices_for_rebuild(client, expiry):
    """
    Compatibility wrapper that returns the last 60 1-minute SPX prices.
    """
    # expiry is currently unused in this wrapper but kept for API compatibility
    return get_historical_minute_bars(client, 60)


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