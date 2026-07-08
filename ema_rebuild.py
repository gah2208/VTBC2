__version__ = "1.1.3"
# copyright (c) Gregory Howard   all rights reserved


# ============================================================
# NEW IMPLEMENTATION (ACTIVE CODE)
# ============================================================

from datetime import datetime, timedelta
import math
from ema_constants import EMA20_SECONDS, EMA5_SECONDS, EMA3_SECONDS

# NEW: Import LOOP from config for consistent dt calculation
from config_loader import load_merged_config

_cfg = load_merged_config()
LOOP = _cfg.get("LOOP", 2)

# NEW: Rebuild uses TradeStation 1-minute historical bars (fixed bar width)
REBUILD_LOOP = 60
EMA_REBUILD_DEPTH = _cfg.get("EMA_REBUILD_DEPTH", 120)


def get_cross_day_minute_prices(client, expiry):
    """
    Fetch enough 1-minute SPX bars to satisfy rebuild depth window.

    Strategy:
        - Pull yesterday's bars from 15:11 → 16:00 (49 bars)
        - Pull today's bars from 09:30 → now
        - Combine until we have >= EMA_REBUILD_DEPTH bars
    """

    prices = []

    # ===== 1. Yesterday 15:11 → 16:00 =====
    # Broker API does not support timestamped queries, so we repeatedly poll
    # until we accumulate the required number of bars.
    #
    # NOTE: This assumes the broker returns the last known SPX price on each call.
    #       This is consistent with the existing get_minute_prices_for_rebuild().
    #
    import time

    # OLD (COMMENTED OUT): hardcoded 49 prefill
    # while len(prices) < 49:

    # UPDATED: keep prior-day prefill bounded by requested rebuild depth
    target_prefill = min(49, EMA_REBUILD_DEPTH)
    while len(prices) < target_prefill:
        spx_data = client.get_spx_price()
        if spx_data:
            prices.append(float(spx_data["Quotes"][0]["Last"]))
        time.sleep(60)

    # ===== 2. Today 09:30 → now =====
    # Continue collecting until we have at least EMA_REBUILD_DEPTH total bars.
    #
    # OLD (COMMENTED OUT): hardcoded 60
    # while len(prices) < 60:
    while len(prices) < EMA_REBUILD_DEPTH:
        spx_data = client.get_spx_price()
        if spx_data:
            prices.append(float(spx_data["Quotes"][0]["Last"]))
        time.sleep(60)

    # OLD (COMMENTED OUT): return prices[-60:]
    return prices[-EMA_REBUILD_DEPTH:]


def rebuild_emas(ema_engine, minute_prices):
    """
    Rebuild EMA state using 1-minute price series.

    Window rules:
        EMA20 = last EMA_REBUILD_DEPTH minutes (configurable)
        EMA5  = last 15 minutes
        EMA3  = last 9 minutes

    UPDATED: Rebuild uses REBUILD_LOOP=60 as dt because source bars are 1-minute bars.
    This keeps rebuild alpha math aligned with TradeStation historical bar width.
    """

    # OLD (COMMENTED OUT): hardcoded 60
    # if len(minute_prices) < 60:
    #     raise Exception("Not enough data to rebuild EMA (need at least 60 minutes)")

    if len(minute_prices) < EMA_REBUILD_DEPTH:
        raise Exception(f"Not enough data to rebuild EMA (need at least {EMA_REBUILD_DEPTH} minutes)")

    now = datetime.now()

    timestamps = []
    for i in range(len(minute_prices)):
        ts = now - timedelta(minutes=(len(minute_prices) - i))
        timestamps.append(ts)

    # ===== EMA20 — last EMA_REBUILD_DEPTH minutes =====
    ema_engine.values[EMA20_SECONDS] = None
    # OLD (COMMENTED OUT): start_20 = max(0, len(minute_prices) - 60)
    start_20 = max(0, len(minute_prices) - EMA_REBUILD_DEPTH)

    for i in range(start_20, len(minute_prices)):
        _update_single(ema_engine, EMA20_SECONDS, minute_prices[i], timestamps[i])

    # ===== EMA5 — last 15 minutes =====
    ema_engine.values[EMA5_SECONDS] = None
    start_5 = max(0, len(minute_prices) - 15)

    for i in range(start_5, len(minute_prices)):
        _update_single(ema_engine, EMA5_SECONDS, minute_prices[i], timestamps[i])

    # ===== EMA3 — last 9 minutes =====
    ema_engine.values[EMA3_SECONDS] = None
    start_3 = max(0, len(minute_prices) - 9)

    for i in range(start_3, len(minute_prices)):
        _update_single(ema_engine, EMA3_SECONDS, minute_prices[i], timestamps[i])


def _update_single(ema_engine, period, price, timestamp):
    """
    Update a single EMA without touching others.

    UPDATED: Uses REBUILD_LOOP=60 as dt for 1-minute historical rebuild bars.
    """

    if ema_engine.last_timestamp is None:
        ema_engine.values[period] = price
        ema_engine.last_timestamp = timestamp
        ema_engine.timestamp_history.append(timestamp.timestamp())
    else:
        prev = ema_engine.values[period]

        if prev is None:
            ema_engine.values[period] = price
        else:
            # OLD (COMMENTED OUT): use live LOOP during rebuild
            # dt = LOOP

            # UPDATED: rebuild dt is fixed at 60 seconds (1-minute bars)
            dt = REBUILD_LOOP

            if dt <= 0:
                return

            tau = ema_engine.taus[period]
            alpha = 1.0 - math.exp(-dt / tau)

            ema_engine.values[period] = prev + alpha * (price - prev)

        # Cap history arrays at 1800 to prevent unbounded growth
        ema_engine.history[period].append(ema_engine.values[period])
        if len(ema_engine.history[period]) > 1800:
            ema_engine.history[period].pop(0)

        ema_engine.last_timestamp = timestamp
        ema_engine.timestamp_history.append(timestamp.timestamp())
        # Cap timestamp history at 1800 to match other history arrays
        if len(ema_engine.timestamp_history) > 1800:
            ema_engine.timestamp_history.pop(0)