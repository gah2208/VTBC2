__version__ = "2.0.0"
# Copyright 2026 Gregory Howard  all rights reserved.

def format_option_symbol(expiry, strike, right):
    """
    Formats a single SPXW option symbol for TradeStation quote endpoints.

    Example:
      SPXW 260707C7485
    """
    right = str(right).upper().strip()
    if right not in ("C", "P"):
        raise ValueError(f"Invalid option right: {right}")

    # Normalize to nearest valid SPX strike increment ($5)
    strike_5 = int(round(float(strike) / 5.0) * 5)

    return f"SPXW {expiry}{right}{strike_5}"

# ============================================================
# NEW: Vertical Spread Builder (Entry)
# ============================================================

def build_vertical_order(expiry, long_strike, short_strike, right, quantity, limit_price):
    """
    Build a 2-leg vertical spread order (entry order).
    This is ALWAYS how VTBC enters trades.

    BUY  long_strike
    SELL short_strike

    Sent as a single bag order.
    """

    long_symbol = format_option_symbol(expiry, long_strike, right)
    short_symbol = format_option_symbol(expiry, short_strike, right)

    return {
        "OrderType": "Limit",
        "LimitPrice": str(limit_price),
        "Legs": [
            {
                "Symbol": long_symbol,
                "TradeAction": "BUY",
                "Quantity": str(quantity)
            },
            {
                "Symbol": short_symbol,
                "TradeAction": "SELL",
                "Quantity": str(quantity)
            }
        ]
    }


# ============================================================
# NEW: Conversion Vertical Builder (Butterfly Creation)
# ============================================================

def build_conversion_order(expiry, short_strike, far_strike, right, quantity, limit_price):
    """
    Build the conversion order that turns a vertical into a butterfly.

    Existing position:
        BUY  L
        SELL S

    Conversion order:
        SELL S
        BUY  far_strike

    After both orders fill:
        BUY  L
        SELL S (x2)
        BUY  far_strike

    This is ALWAYS a 2-leg vertical spread.
    """

    short_symbol = format_option_symbol(expiry, short_strike, right)
    far_symbol = format_option_symbol(expiry, far_strike, right)

    return {
        "OrderType": "Limit",
        "LimitPrice": str(limit_price),
        "Legs": [
            {
                "Symbol": short_symbol,
                "TradeAction": "SELL",
                "Quantity": str(quantity)
            },
            {
                "Symbol": far_symbol,
                "TradeAction": "BUY",
                "Quantity": str(quantity)
            }
        ]
    }
