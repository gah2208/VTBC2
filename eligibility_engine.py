__version__ = "1.5.2"

# copyright (c) Gregory Howard  2026 all rights reserved

from config_loader import load_merged_config
from ema_constants import EMA3_SECONDS, EMA5_SECONDS, EMA20_SECONDS

_cfg = load_merged_config()
NOISE_3_5 = _cfg.get("NOISE_3_5", 0.25)
NOISE_5_20 = _cfg.get("NOISE_5_20", 0.25)
MIN_EM = _cfg.get("MIN_EM", 8)


def check_min_em(option_mid, min_em_threshold):
    """
    Option-1 expected-move qualifier:
    use ATM single-leg option mid for the eligible direction (C or P).
    """
    if option_mid is None:
        return False
    return option_mid >= min_em_threshold


def evaluate_trade(spx_price, surface, ema_engine):
    """
    Determine if a trade should be placed based on current market conditions.

    Returns: dict with "direction" (C or P) if trade should be placed, else None
    """

    # NEW: Use EMA constants explicitly instead of relying on dict key order
    ema3 = ema_engine.get(EMA3_SECONDS)
    ema5 = ema_engine.get(EMA5_SECONDS)
    ema20 = ema_engine.get(EMA20_SECONDS)

    # Handle None EMAs (not yet initialized)
    if ema3 is None or ema5 is None or ema20 is None:
        return None

    # ATM strike
    atm = surface["atm"]

    # ===== NOISE THRESHOLDS =====
    # NOISE_3_5: noise threshold between EMA3 and EMA5
    # NOISE_5_20: noise threshold between EMA5 and EMA20

    noise_3_5 = abs(ema3 - ema5)
    noise_5_20 = abs(ema5 - ema20)

    # ===== TRADE RULES =====
    # Call: EMA3 > EMA5 > EMA20 (bullish) + outside noise band
    # Put:  EMA3 < EMA5 < EMA20 (bearish) + outside noise band

    # OBSOLETE (COMMENTED OUT): inside-noise logic
    # if (ema3 > ema5 > ema20 and
    #     noise_3_5 < NOISE_3_5 and
    #     noise_5_20 < NOISE_5_20):
    #     return {"direction": "C"}

    # if (ema3 < ema5 < ema20 and
    #     noise_3_5 < NOISE_3_5 and
    #     noise_5_20 < NOISE_5_20):
    #     return {"direction": "P"}

    # UPDATED PER REQUEST: outside-noise logic
    if (ema3 > ema5 > ema20 and
        noise_3_5 > NOISE_3_5 and
        noise_5_20 > NOISE_5_20):
        return {"direction": "C"}

    if (ema3 < ema5 < ema20 and
        noise_3_5 > NOISE_3_5 and
        noise_5_20 > NOISE_5_20):
        return {"direction": "P"}

    return None