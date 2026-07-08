__version__ = "1.3.0"
# Copyright 2026 Gregory Howard  all rights reserved.

from enum import Enum
from datetime import datetime, timedelta

# NEW: Import ORDER_TIMEOUT from config
from config_loader import load_merged_config

_cfg = load_merged_config()
ORDER_TIMEOUT = _cfg.get("ORDER_TIMEOUT", 180)

class State(Enum):
    IDLE = 0
    LONG_WORKING = 1
    CONVERSION_WORKING = 2

class ExecutionState:
    def __init__(self):
        self.state = State.IDLE
        self.order_id = None
        self.deadline = None
        self.long_strike = None
        self.short_strike = None
        self.qty = 0
        self.direction = None
        self.entry_price = None
        self.active_positions = []

    def submit_long(self, oid, long_strike, short_strike, qty, direction, price):
        self.state = State.LONG_WORKING
        self.order_id = oid
        self.long_strike = long_strike
        self.short_strike = short_strike
        self.qty = qty
        self.direction = direction
        self.entry_price = price
        self.deadline = datetime.now() + timedelta(seconds=ORDER_TIMEOUT)

    def check_long(self, status):
        if status == "FILLED":
            return "FILLED"
        if datetime.now() >= self.deadline:
            return "CANCEL"
        return "WAIT"

    def submit_conversion(self, oid):
        self.state = State.CONVERSION_WORKING
        self.order_id = oid
        self.deadline = datetime.now() + timedelta(seconds=ORDER_TIMEOUT)

    def check_conversion(self, status):
        if status == "FILLED":
            return "DONE"
        return "WAIT"

    def add_position(self, direction, long_strike, short_strike, entry_price, qty):
        """
        Record a filled long vertical spread position.
        entry_price and qty are stored per-position as they are the
        basis for all subsequent force-exit conversion pricing.
        conversion_order tracks any active force-exit short vertical
        order placed against this position (None until placed).
        """
        self.active_positions.append({
            "direction": direction,
            "long_strike": long_strike,
            "long_strikes": [long_strike],   # retained for trade_conflicts schema
            "short_strike": short_strike,
            "short_strikes": [short_strike], # retained for trade_conflicts schema
            "base_short": short_strike,
            "entry_price": entry_price,
            "qty": qty,
            "conversion_order": None         # set when a force-exit conversion is placed
        })

    def count_active(self, direction):
        return sum(1 for p in self.active_positions if p.get("direction") == direction)

    def get_active_positions(self):
        return list(self.active_positions)