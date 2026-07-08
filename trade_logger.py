__version__ = "1.0.2"

# copyright (c) Gregory Howard  2026  all rights reserved

import os
import csv
from datetime import datetime

# NEW: Import from config_loader to get LOG_DIR if needed
from config_loader import load_merged_config

_cfg = load_merged_config()
LOG_DIR = _cfg.get("LOG_DIR", ".")
TRADE_LOG_FILE = os.path.join(LOG_DIR, "trade_log.csv")


def log_event(event_type, spx_price, direction, strike, spread_width, order_id=None, details=None):
    """
    Log a trade event to trade_log.csv.
    
    Fields:
        - timestamp (YYYY-MM-DD HH:MM:SS)
        - event_type
        - spx_price
        - direction (C or P)
        - strike
        - spread_width
        - order_id
        - details
    """

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    row = [
        timestamp,
        event_type,
        spx_price,
        direction,
        strike,
        spread_width,
        order_id,
        details
    ]

    try:
        file_exists = os.path.exists(TRADE_LOG_FILE)

        with open(TRADE_LOG_FILE, "a", newline="") as f:
            writer = csv.writer(f)

            if not file_exists:
                writer.writerow([
                    "timestamp",
                    "event_type",
                    "spx_price",
                    "direction",
                    "strike",
                    "spread_width",
                    "order_id",
                    "details"
                ])

            writer.writerow(row)

    except Exception as e:
        print(f"Failed to log event: {e}")