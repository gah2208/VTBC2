__version__ = "1.0.0"
# Copyright 2026 Gregory Howard  all rights reserved.

"""
trade_conflicts.py

Helper module for detecting strike conflicts between a proposed butterfly
and existing positions (verticals or butterflies) in the same direction.

Conflict rules (direction-specific, CALL or PUT):

A proposed trade with strikes (pL1, pS, pL2) conflicts with an existing trade if:

1) The proposed SHORT strike intersects with any existing LONG strike
   (including the implied future long of a vertical).

2) The proposed LONG strikes intersect with any existing SHORT strike
   (including the current short of a vertical, which will remain short
   after conversion to a butterfly).

We explicitly DO NOT treat long–long overlap as a conflict; overlapping
wings are allowed. Only long–short and short–long overlaps matter.
"""


def _extract_effective_strikes(trade, spread_width):
    """
    Normalize an existing trade into effective long/short strike sets,
    taking into account future conversion of verticals into butterflies.

    Expected trade structure (dict-like):

        {
            "direction": "C" or "P",
            "long_strikes": [ ... ],   # current long strikes (1 for vertical, 2 for butterfly)
            "short_strikes": [ ... ],  # current short strikes (1 for vertical, 2 for butterfly)
            "base_short": K_short      # optional, used to infer future wing for verticals
        }

    Rules:

    - For butterflies:
        long_strikes = [L1, L2]
        short_strikes = [S, S] or [S] (depending on representation)
        No future conversion; structure is already complete.

    - For verticals:
        long_strikes = [L]
        short_strikes = [S]
        base_short = S

        Future butterfly (CALL):
            Long L
            Short S (x2)
            Long (S + spread_width)

        Future butterfly (PUT):
            Long L
            Short S (x2)
            Long (S - spread_width)

        So effective long set includes:
            - current long(s)
            - implied future long wing

        Effective short set includes:
            - current short(s)
            (future second short is at the same strike as base_short)
    """

    longs = set(trade.get("long_strikes", []))
    shorts = set(trade.get("short_strikes", []))

    direction = trade.get("direction")
    base_short = trade.get("base_short", None)

    # If we have exactly one long and one short and a base_short,
    # treat this as a vertical and infer the future wing.
    if base_short is not None and len(longs) == 1 and len(shorts) == 1:
        if direction == "C":
            future_long = base_short + spread_width
        elif direction == "P":
            future_long = base_short - spread_width
        else:
            future_long = None

        if future_long is not None:
            longs.add(future_long)

        # shorts already contain base_short; future second short is at same strike,
        # so no need to add anything extra.

    return longs, shorts


def has_conflict(existing_trades, direction, proposed_strikes, spread_width):
    """
    Determine whether a proposed butterfly conflicts with existing trades
    in the same direction.

    Parameters
    ----------
    existing_trades : iterable
        Collection of existing trades. Each trade should be a dict-like object
        with at least:
            - "direction": "C" or "P"
            - "long_strikes": list of long strike prices
            - "short_strikes": list of short strike prices
            - "base_short": strike of the primary short (for verticals)

    direction : str
        "C" for calls, "P" for puts. Direction of the proposed trade.

    proposed_strikes : tuple or list
        (pL1, pS, pL2) for the proposed butterfly:
            pL1 = lower long strike
            pS  = short strike (center)
            pL2 = upper long strike

    spread_width : int or float
        The spread width (SPREAD_WIDTH) used to infer future wings for verticals.

    Returns
    -------
    bool
        True if there is a conflict, False otherwise.

    Conflict conditions:

        1) Proposed SHORT vs existing LONG:
               pS in effective_long_strikes

        2) Proposed LONG vs existing SHORT:
               pL1 in effective_short_strikes
            or pL2 in effective_short_strikes

        Overlapping longs (pL1/pL2 vs existing longs) are allowed and
        do NOT constitute a conflict.
    """

    if not proposed_strikes or len(proposed_strikes) != 3:
        # If we don't have a proper butterfly structure, be conservative.
        return True

    pL1, pS, pL2 = proposed_strikes

    for trade in existing_trades:

        # Only consider trades in the same direction (CALL or PUT).
        if trade.get("direction") != direction:
            continue

        effective_longs, effective_shorts = _extract_effective_strikes(trade, spread_width)

        # Condition 1: proposed SHORT intersects any existing LONG (including future wings).
        if pS in effective_longs:
            return True

        # Condition 2: proposed LONG intersects any existing SHORT (including vertical shorts).
        if pL1 in effective_shorts or pL2 in effective_shorts:
            return True

    return False
