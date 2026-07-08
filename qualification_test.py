#!/usr/bin/env python3
"""
Qualification gate unit tests for VTBC.
Tests MIN_EM gate, quote validation, and premium/width gating behavior
using mock client objects — no live API access required.
Run with: python qualification_test.py
"""
# Copyright 2026 Gregory Howard  all rights reserved.
import sys
import os
# Ensure we can import from the repo root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eligibility_engine import check_min_em
from market_data import get_option_quote, get_spread_quote
from order_builder import format_option_symbol
# ============================================================
# Test runner helpers
# ============================================================
_pass = 0
_fail = 0
def _test(name, condition, detail=""):
    global _pass, _fail
    if condition:
        print(f"  ✅ PASS  {name}")
        _pass += 1
    else:
        print(f"  ❌ FAIL  {name}" + (f"  —  {detail}" if detail else ""))
        _fail += 1
# ============================================================
# Minimal mock client (no API calls)
# ============================================================
class _QuoteClient:
    """Returns a fixed single-symbol quote response."""
    def __init__(self, bid, ask, symbol=None):
        self._bid = bid
        self._ask = ask
        self._symbol = symbol
    def get_quotes(self, symbols):
        sym = self._symbol or symbols[0]
        return {"Quotes": [{"Symbol": sym, "Bid": self._bid, "Ask": self._ask}]}
class _SpreadClient:
    """Returns a fixed two-symbol quote response for spread tests."""
    def __init__(self, long_bid, long_ask, short_bid, short_ask,
                 expiry, long_k, short_k, right):
        self._long_sym  = format_option_symbol(expiry, long_k,  right)
        self._short_sym = format_option_symbol(expiry, short_k, right)
        self._quotes = [
            {"Symbol": self._long_sym,  "Bid": long_bid,  "Ask": long_ask},
            {"Symbol": self._short_sym, "Bid": short_bid, "Ask": short_ask},
        ]
    def get_quotes(self, symbols):
        return {"Quotes": self._quotes}
class _EmptyClient:
    """Simulates a client that returns an empty/missing response."""
    def get_quotes(self, symbols):
        return {}
class _ErrorClient:
    """Simulates a client that raises an exception."""
    def get_quotes(self, symbols):
        raise ConnectionError("simulated network failure")
# ============================================================
# SECTION 1 — check_min_em  (MIN_EM gate)
# ============================================================
print("\n[SECTION 1] check_min_em — MIN_EM gate")
_test("mid >= threshold passes",        check_min_em(9.00, 8))
_test("mid == threshold passes",        check_min_em(8.00, 8))
_test("mid < threshold fails",     not  check_min_em(7.99, 8))
_test("mid = 0 fails",             not  check_min_em(0,    8))
_test("mid = None fails",          not  check_min_em(None, 8))
_test("large mid passes",               check_min_em(25.0, 8))
_test("threshold = 0 always passes",    check_min_em(0.01, 0))
# ============================================================
# SECTION 2 — get_option_quote  (quote validation)
# ============================================================
print("\n[SECTION 2] get_option_quote — quote validation")
EXPIRY = "260628"
STRIKE = 5500
RIGHT  = "C"
# Valid quote
q = get_option_quote(_QuoteClient(4.0, 6.0), EXPIRY, STRIKE, RIGHT)
_test("valid quote returns dict",            q is not None)
_test("mid is correct (bid+ask)/2 = 5.0",   q is not None and q["mid"] == 5.0)
_test("bid/ask preserved in result",
      q is not None and q["bid"] == 4.0 and q["ask"] == 6.0)
# ask = 0
_test("ask=0 returns None",
      get_option_quote(_QuoteClient(0.0, 0.0), EXPIRY, STRIKE, RIGHT) is None)
# inverted quote (ask < bid)
_test("inverted quote returns None",
      get_option_quote(_QuoteClient(6.0, 4.0), EXPIRY, STRIKE, RIGHT) is None)
# empty response
_test("empty response returns None",
      get_option_quote(_EmptyClient(), EXPIRY, STRIKE, RIGHT) is None)
# network error
_test("exception returns None (no crash)",
      get_option_quote(_ErrorClient(), EXPIRY, STRIKE, RIGHT) is None)
# bid=0, ask>0 — valid (one-sided market for deep OTM is acceptable)
q2 = get_option_quote(_QuoteClient(0.0, 1.0), EXPIRY, STRIKE, RIGHT)
_test("bid=0 ask>0 returns valid quote",     q2 is not None)
_test("mid = 0.5 when bid=0 ask=1",          q2 is not None and q2["mid"] == 0.5)
# ============================================================
# SECTION 3 — get_spread_quote  (spread quote validation)
# ============================================================
print("\n[SECTION 3] get_spread_quote — spread validation")
LONG_K  = 5500
SHORT_K = 5510
def _sc(lb, la, sb, sa):
    return _SpreadClient(lb, la, sb, sa, EXPIRY, LONG_K, SHORT_K, RIGHT)
# Valid spread: long=5.0/6.0, short=2.0/2.5
# spread_bid = 5.0 - 2.5 = 2.5
# spread_ask = 6.0 - 2.0 = 4.0
# spread_mid = (2.5 + 4.0) / 2 = 3.25
sq = get_spread_quote(_sc(5.0, 6.0, 2.0, 2.5), EXPIRY, LONG_K, SHORT_K, RIGHT)
_test("valid spread returns dict",           sq is not None)
_test("spread_bid = 2.5",                    sq is not None and sq["bid"] == 2.5)
_test("spread_ask = 4.0",                    sq is not None and sq["ask"] == 4.0)
_test("spread_mid = 3.25",                   sq is not None and sq["mid"] == 3.25)
# long_ask = 0
_test("zero long_ask returns None",
      get_spread_quote(_sc(0.0, 0.0, 2.0, 2.5), EXPIRY, LONG_K, SHORT_K, RIGHT) is None)
# spread_ask <= 0: long_ask(1.5) < short_bid(3.0) → spread_ask = 1.5-3.0 = -1.5
_test("spread_ask <= 0 returns None",
      get_spread_quote(_sc(1.0, 1.5, 3.0, 3.5), EXPIRY, LONG_K, SHORT_K, RIGHT) is None)
# empty response
_test("empty response returns None",
      get_spread_quote(_EmptyClient(), EXPIRY, LONG_K, SHORT_K, RIGHT) is None)
# exception
_test("exception returns None (no crash)",
      get_spread_quote(_ErrorClient(), EXPIRY, LONG_K, SHORT_K, RIGHT) is None)
# ============================================================
# SECTION 4 — Premium and bid-ask width gating
# Replicates the exact gating logic from main.py
# ============================================================
print("\n[SECTION 4] Premium and bid-ask width gating")
def _gate(mid, ask, bid, max_premium_cents=200, slippage=0.05, ba_limit=2.0):
    """
    Returns the gate result string:
      "PASS" | "FAIL_WIDTH" | "FAIL_MID_ZERO" | "FAIL_PREMIUM"
    Mirrors the qualification checks in main.py lines 521-536.
    """
    bid_ask_width = ask - bid
    if bid_ask_width >= ba_limit:
        return "FAIL_WIDTH"
    if mid <= 0:
        return "FAIL_MID_ZERO"
    premium_cap = (max_premium_cents / 100) + slippage
    if mid >= premium_cap:
        return "FAIL_PREMIUM"
    return "PASS"
_test("valid spread passes all gates",
      _gate(mid=1.50, ask=2.00, bid=1.00) == "PASS")
_test("bid-ask width exactly at limit fails  (>= limit)",
      _gate(mid=1.50, ask=3.00, bid=1.00) == "FAIL_WIDTH")
_test("bid-ask width above limit fails",
      _gate(mid=1.50, ask=4.00, bid=1.00) == "FAIL_WIDTH")
_test("bid-ask width just under limit passes",
      _gate(mid=1.50, ask=2.99, bid=1.00) == "PASS")
_test("mid equals premium_cap fails  (>= cap)",
      _gate(mid=2.05, ask=2.50, bid=1.50) == "FAIL_PREMIUM")
_test("mid above premium_cap fails",
      _gate(mid=3.00, ask=3.50, bid=2.50) == "FAIL_PREMIUM")
_test("mid just under premium_cap passes",
      _gate(mid=2.04, ask=2.50, bid=1.50) == "PASS")
_test("mid = 0 fails",
      _gate(mid=0.00, ask=0.50, bid=0.50) == "FAIL_MID_ZERO")
_test("custom tight ba_limit fails at width 1.0",
      _gate(mid=1.00, ask=2.00, bid=1.00, ba_limit=1.0) == "FAIL_WIDTH")
_test("custom tight premium_cap=100cents+0.05slippage",
      _gate(mid=1.06, ask=1.50, bid=1.00, max_premium_cents=100) == "FAIL_PREMIUM")
# ============================================================
# SECTION 5 — get_atm_surface  (STRIKE_STEP rounding)
# ============================================================
print("\n[SECTION 5] get_atm_surface — STRIKE_STEP rounding")
from market_data import get_atm_surface, STRIKE_STEP
class _DummyClient:
    pass
def _atm(spx_price):
    return get_atm_surface(_DummyClient(), "260628", spx_price)["atm"]
# With default STRIKE_STEP=5:
# 5502.30 → round(5502.30/5)*5 = round(1100.46)*5 = 1100*5 = 5500
# 5507.50 → round(5507.50/5)*5 = round(1101.5)*5 = 1102*5 = 5510 (banker's rounding: even)
# 5505.00 → round(5505.00/5)*5 = round(1101.0)*5 = 1101*5 = 5505
_test("STRIKE_STEP is integer",          isinstance(STRIKE_STEP, int))
_test("ATM divisible by STRIKE_STEP",    _atm(5502.30) % STRIKE_STEP == 0)
_test("5502.30 → 5500",                  _atm(5502.30) == 5500)
_test("5505.00 → 5505",                  _atm(5505.00) == 5505)
_test("5497.49 → 5495",                  _atm(5497.49) == 5495)
_test("exact strike unchanged",          _atm(5510.00) == 5510)
# ============================================================
# Summary
# ============================================================
total = _pass + _fail
print(f"\n{'=' * 52}")
print(f"Results: {_pass}/{total} passed  ({_fail} failed)")
if _fail > 0:
    print("❌ SOME TESTS FAILED")
    sys.exit(1)
print("✅ ALL TESTS PASSED")
sys.exit(0)