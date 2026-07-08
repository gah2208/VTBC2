__version__ = "1.2.2"
# copyright (c) Gregory Howard 2026  all rights reserved


# ============================================================
#  NEW CODE (ACTIVE IMPLEMENTATION)
# ============================================================

from datetime import datetime
import math
from ema_constants import EMA20_SECONDS, EMA5_SECONDS, EMA3_SECONDS


class EMAEngine:

    def __init__(self, ema_seconds_list, loop):
        """
        ema_seconds_list: list of EMA durations in seconds
        loop: sampling interval (from merged JSON config)
        """

        self.targets = ema_seconds_list
        self.loop = loop  # NEW: LOOP passed in from bootstrap

        # tau = EMA time constant (same as period in your design)
        self.taus = {t: float(t) for t in ema_seconds_list}

        self.values = {t: None for t in ema_seconds_list}
        self.last_timestamp = None

        # optional slope history storage
        self.history = {t: [] for t in ema_seconds_list}

        # timestamp history for slope
        self.timestamp_history = []

    # ============================================================
    #  NEW: load_state() for bootstrap seeding (FIXED M-2)
    # ============================================================
    def load_state(self, ema3, ema5, ema20, timestamp=None):
        """
        Load EMA state from persisted data.
        
        NEW (M-2 FIX): Now actually assigns the provided EMA values instead of ignoring them.
        This makes the API less fragile and more intuitive.
        """

        if timestamp is None:
            timestamp = datetime.now()

        # NEW: Actually assign the EMA values that were passed in
        self.values[EMA3_SECONDS] = ema3
        self.values[EMA5_SECONDS] = ema5
        self.values[EMA20_SECONDS] = ema20

        self.last_timestamp = timestamp
        self.timestamp_history.append(timestamp.timestamp())

        # NEW: cap timestamp history
        if len(self.timestamp_history) > 1800:
            self.timestamp_history.pop(0)

    # ============================================================
    #  update() logic with dt = LOOP and 1800 caps
    # ============================================================
    def update(self, price, timestamp=None):

        if timestamp is None:
            timestamp = datetime.now()

        if self.last_timestamp is None:
            # initialize all EMAs to first price
            for t in self.targets:
                self.values[t] = price
                self.history[t].append(price)

                # NEW: cap history
                if len(self.history[t]) > 1800:
                    self.history[t].pop(0)

            self.last_timestamp = timestamp
            self.timestamp_history.append(timestamp.timestamp())

            # NEW: cap timestamp history
            if len(self.timestamp_history) > 1800:
                self.timestamp_history.pop(0)

            return

        # OLD (commented out)
        # dt = (timestamp - self.last_timestamp).total_seconds()

        # NEW: dt is always LOOP
        dt = self.loop

        for t in self.targets:

            tau = self.taus[t]
            alpha = 1.0 - math.exp(-dt / tau)

            prev = self.values[t]

            if prev is None:
                self.values[t] = price
            else:
                self.values[t] = prev + alpha * (price - prev)

            # OLD (commented out)
            # self.history[t].append(self.values[t])

            # NEW: append + cap at 1800
            self.history[t].append(self.values[t])
            if len(self.history[t]) > 1800:
                self.history[t].pop(0)

        self.last_timestamp = timestamp

        self.timestamp_history.append(timestamp.timestamp())
        if len(self.timestamp_history) > 1800:
            self.timestamp_history.pop(0)

    def get(self, seconds):
        return self.values.get(seconds)

    def get_all(self):
        return self.values.copy()

    def get_slope(self, seconds, lookback_seconds):

        series = self.history.get(seconds, [])
        timestamps = self.timestamp_history

        if len(series) < 2 or len(timestamps) < 2:
            return 0.0

        now_time = timestamps[-1]
        target_time = now_time - lookback_seconds

        idx = 0
        for i in range(len(timestamps) - 1, -1, -1):
            if timestamps[i] <= target_time:
                idx = i
                break

        dt = now_time - timestamps[idx]

        if dt <= 0:
            return 0.0

        return (series[-1] - series[idx]) / dt