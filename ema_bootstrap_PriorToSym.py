__version__ = "1.1.2"

# copyright (c) Gregory Howard  2026 all rights reserved

from datetime import datetime

from ema_engine import EMAEngine
from ema_rebuild import rebuild_emas
from ema_persistence import load_ema_state, is_stale, save_ema_state
from ema_constants import EMA3_SECONDS, EMA5_SECONDS, EMA20_SECONDS

# We still rely on market_data for 1-minute bars
from market_data import get_minute_prices_for_rebuild

# NEW: load merged JSON config (correct source of LOOP)
from config_loader import load_merged_config


def initialize_ema_engine(client, expiry):
    """
    Initialize EMAEngine according to the correct design:

    1) Load merged JSON config (admin_config_default.json + config.json)
       and extract LOOP.

    2) Try to load previous EMA state.
       - If present and not stale → seed EMAs from it.

    3) Otherwise, poll broker for 1-minute SPX data (≥60 minutes)
       and rebuild EMAs from that.

    This ensures EMAs start the day anchored correctly.
    """

    config = load_merged_config()
    loop = config["LOOP"]

    # Instantiate EMAEngine before using it
    ema_engine = EMAEngine([EMA3_SECONDS, EMA5_SECONDS, EMA20_SECONDS], loop)


    # ------------------------------------------------------------
    # 1) Try persistence first
    # ------------------------------------------------------------
    state = load_ema_state()

    if state and not is_stale(state):

        # Seed values directly from persisted state
        ema_engine.values[EMA3_SECONDS] = state.get("ema3")
        ema_engine.values[EMA5_SECONDS] = state.get("ema5")
        ema_engine.values[EMA20_SECONDS] = state.get("ema20")

        # NEW: timestamp is now epoch seconds (integer) - convert directly
        saved_ts = state.get("timestamp")
        if saved_ts and isinstance(saved_ts, (int, float)):
            try:
                persisted_ts = datetime.fromtimestamp(saved_ts)
            except Exception:
                persisted_ts = datetime.now()
        else:
            persisted_ts = datetime.now()

        # OLD CODE (COMMENTED OUT)
        # persisted_ts = state.get("timestamp")
        # if persisted_ts:
        #     persisted_ts = datetime.fromtimestamp(persisted_ts)
        # else:
        #     persisted_ts = datetime.now()

        ema_engine.load_state(
            ema3=state.get("ema3"),
            ema5=state.get("ema5"),
            ema20=state.get("ema20"),
            timestamp=persisted_ts
        )

        return ema_engine

    # ------------------------------------------------------------
    # 2) Fallback: broker 1-minute data (need ≥60 minutes)
    # ------------------------------------------------------------
    prices = get_minute_prices_for_rebuild(client, expiry)

    if not prices or len(prices) < 60:
        raise Exception("Not enough historical data to initialize EMAs (need ≥60 1-minute bars)")

    # Use only the last 60 minutes (correct for EMA20 warm-up)
    prices = prices[-60:]

    rebuild_emas(ema_engine, prices)

    # NEW: save rebuilt state
    save_ema_state(ema_engine)

    return ema_engine


def reseed_after_gap(client, expiry, ema_engine):
    """
    Rebuild EMAs after a trading halt or multi-day outage.

    Design:
    - Poll broker for last 60 minutes of 1-minute SPX data.
    - Rebuild EMAs from that window.
    """

    prices = get_minute_prices_for_rebuild(client, expiry)

    if not prices or len(prices) < 60:
        raise Exception("Not enough historical data to reseed EMAs (need ≥60 1-minute bars)")

    prices = prices[-60:]

    rebuild_emas(ema_engine, prices)

    # NEW: save rebuilt state
    save_ema_state(ema_engine)