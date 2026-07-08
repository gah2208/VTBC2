# main.py
# NEW: Device-ID auth + EXE checksum enforcement (startup + 09:00 ET M-F)
__version__ = "1.3.3"
# OLD VERSION (COMMENTED OUT): old___version__ = "1.3.1"

# Ensure merged config.py exists before importing modules that expect flat config constants
# DISABLED: config.py is always provided in the root directory.
# try:
#     from config_gen import generate_config_py
#     generate_config_py()
# except Exception as e:
#     print(f"Warning: failed to generate config.py at startup: {e}")

# Optional non-fatal assertion to detect drift between merged JSON and generated config.py
# DISABLED PER REQUEST
# try:
#     if load_merged_config is not None:
#         merged = load_merged_config()
#         if getattr(_cfg, "CONFIG", None) != merged:
#             print("Warning: provided config.py differs from merged config.json + admin defaults.")
# except Exception:
#     pass

try:
    from config_loader import load_merged_config
except Exception:
    load_merged_config = None

import math
import time
import socket
import requests
import ctypes
import sys
import os
import json
import hashlib
import importlib.util
# NEW IMPORTS FOR DEVICE ID
import subprocess
import uuid
from datetime import datetime

# ===== CONFIG LOADING FROM ROOT DIRECTORY (NOT _MEI TEMP) =====
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(APP_DIR, "config.py")
if not os.path.exists(CONFIG_PATH):
    raise FileNotFoundError(f"config.py not found at: {CONFIG_PATH}")

_cfg_spec = importlib.util.spec_from_file_location("config_runtime", CONFIG_PATH)
_cfg = importlib.util.module_from_spec(_cfg_spec)
_cfg_spec.loader.exec_module(_cfg)

required_config_keys = [
    "API_KEY",
    "REFRESH_TOKEN",
    "ACCOUNT_ID",
    "ENABLE_LIVE_TRADING",
    "PUSHOVER_USER_KEY",
    "PUSHOVER_API_TOKEN",
    "ADMIN_PUSHOVER_USER_KEY",
    "ADMIN_PUSHOVER_API_TOKEN",
    "PUSHOVER_ENABLED",
    "WINDOWS_ALERT_ENABLED",
    "STRIKE_STEP",
    "SPREAD_WIDTH",
    "MARKET_OPEN_TIME",
    "TRADE_START_TIME",
    "STOP_NEW_ENTRIES",
    "FORCE_EXIT_TIME",
    "FORCE_EXIT_ENABLED",
    "ORDER_TIMEOUT",
    "LOOP",
    "MIN_EM",
    "MAX_PREMIUM",
    "SLIPPAGE",
    "BID_ASK_SPREAD",
    "POSITIONS",
    "ACCOUNT_CAPITAL",
    "MAX_CALLS_ACTIVE",
    "MAX_PUTS_ACTIVE",
]
missing = [k for k in required_config_keys if not hasattr(_cfg, k)]
if missing:
    raise ImportError(f"config.py missing required keys: {', '.join(missing)}")

API_KEY = _cfg.API_KEY
REFRESH_TOKEN = _cfg.REFRESH_TOKEN
ACCOUNT_ID = _cfg.ACCOUNT_ID
ENABLE_LIVE_TRADING = _cfg.ENABLE_LIVE_TRADING
PUSHOVER_USER_KEY = _cfg.PUSHOVER_USER_KEY
PUSHOVER_API_TOKEN = _cfg.PUSHOVER_API_TOKEN
ADMIN_PUSHOVER_USER_KEY = _cfg.ADMIN_PUSHOVER_USER_KEY
ADMIN_PUSHOVER_API_TOKEN = _cfg.ADMIN_PUSHOVER_API_TOKEN
PUSHOVER_ENABLED = _cfg.PUSHOVER_ENABLED
WINDOWS_ALERT_ENABLED = _cfg.WINDOWS_ALERT_ENABLED
STRIKE_STEP = _cfg.STRIKE_STEP
SPREAD_WIDTH = _cfg.SPREAD_WIDTH
MARKET_OPEN_TIME = _cfg.MARKET_OPEN_TIME
TRADE_START_TIME = _cfg.TRADE_START_TIME
STOP_NEW_ENTRIES = _cfg.STOP_NEW_ENTRIES
FORCE_EXIT_TIME = _cfg.FORCE_EXIT_TIME
FORCE_EXIT_ENABLED = _cfg.FORCE_EXIT_ENABLED
ORDER_TIMEOUT = _cfg.ORDER_TIMEOUT
LOOP = _cfg.LOOP
MIN_EM = _cfg.MIN_EM
MAX_PREMIUM = _cfg.MAX_PREMIUM
SLIPPAGE = _cfg.SLIPPAGE
BID_ASK_SPREAD = _cfg.BID_ASK_SPREAD
POSITIONS = _cfg.POSITIONS
ACCOUNT_CAPITAL = _cfg.ACCOUNT_CAPITAL
MAX_CALLS_ACTIVE = _cfg.MAX_CALLS_ACTIVE
MAX_PUTS_ACTIVE = _cfg.MAX_PUTS_ACTIVE

from ts_client import TSClient
from execution_state import ExecutionState, State
from order_builder import build_vertical_order
from market_data import get_atm_surface, get_minute_prices_for_rebuild, get_option_quote, get_spread_quote
from eligibility_engine import evaluate_trade, check_min_em
from trade_conflicts import has_conflict
# OLD EMA IMPORTS (COMMENTED OUT)
# from ema_engine import EMAEngine
# from ema_rebuild import rebuild_emas
from trade_logger import log_event

from build_check import run_build_check
from license import check_license

# NEW EMA IMPORTS
from ema_bootstrap import initialize_ema_engine
from ema_persistence import save_ema_state
from ema_constants import EMA3_SECONDS, EMA5_SECONDS, EMA20_SECONDS

# ===== NEW: DEVICE ID HELPERS =====
def get_device_id():
    """
    Returns a stable device identifier.
    Priority:
      1) Windows MachineGuid (preferred)
      2) uuid.getnode() fallback
    """
    try:
        out = subprocess.check_output(
            ["reg", "query", r"HKLM\SOFTWARE\Microsoft\Cryptography", "/v", "MachineGuid"],
            stderr=subprocess.DEVNULL,
            text=True
        )
        for line in out.splitlines():
            if "MachineGuid" in line:
                parts = line.split()
                if parts:
                    return parts[-1].strip()
    except Exception:
        pass

    try:
        return str(uuid.getnode())
    except Exception:
        return "UNKNOWN_DEVICE_ID"

# ===== NEW: EXE CHECKSUM CONFIG =====
CS_TARGET_DIR = APP_DIR
CS_JSON_PATH = os.path.join(APP_DIR, "cs.json")
EXE_CHECKSUM_MAP = {
    "abort.exe": "abort_cs",
    "config_editor.exe": "config_editor_cs",
    "main.exe": "main_cs",
    "rollback.exe": "rollback_cs",
    "update.exe": "update_cs",
}

def verify_runtime_exe_checksums(cs_json_path=CS_JSON_PATH, target_dir=CS_TARGET_DIR):
    """
    Validate hashes in cs.json against runtime EXEs in root app directory.
    Returns (ok: bool, failing_exe: str|None, reason: str)
    """
    if not os.path.exists(cs_json_path):
        return False, "cs.json", f"Missing checksum file: {cs_json_path}"

    try:
        with open(cs_json_path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except Exception as e:
        return False, "cs.json", f"Unable to parse cs.json: {e}"

    for exe_name, key_name in EXE_CHECKSUM_MAP.items():
        exe_path = os.path.join(target_dir, exe_name)

        expected = str(data.get(key_name, "")).strip().lower()
        if not expected:
            return False, exe_name, f"Missing/empty key '{key_name}' in cs.json"

        if not os.path.exists(exe_path):
            return False, exe_name, f"Missing file: {exe_path}"

        actual = _sha256(exe_path).lower()
        if actual != expected:
            return False, exe_name, f"Checksum mismatch for {exe_name}"

    return True, None, "All runtime EXE checksums match."

def enforce_runtime_integrity():
    """
    If checksum compare fails:
      - suspend trading (safe mode)
      - alert user and admin with requested message formats
    """
    global system_safe_mode

    ok, failing_exe, reason = verify_runtime_exe_checksums()
    if ok:
        return True

    system_safe_mode = True

    user_msg = f"Data corruption in {failing_exe}.  Trading suspended"
    device_id = get_device_id()
    admin_msg = f"{user_msg}\nCorruption found on computer '{device_id}'"

    print(f"RUNTIME INTEGRITY FAILURE: {reason}")
    send_alert(user_msg)
    send_admin_alert(admin_msg)

    try:
        log_event("CHECKSUM_FAIL", None, None, None, None, details=reason)
    except Exception:
        pass

    return False


# ===== UNAUTHORIZED HANDLER (UPDATED TO DEVICE ID) =====
def handle_unauthorized():

    # OLD USER ID LOGIC (COMMENTED OUT)
    # user_id = socket.gethostname()
    # NEW DEVICE ID LOGIC
    device_id = get_device_id()

    # OLD MESSAGE (COMMENTED OUT)
    # msg = f"""
    # VTBC NOT AUTHORIZED
    #
    # User ID:
    # {user_id}
    #
    # Contact administrator for access.
    # """
    msg = f"""
VTBC NOT AUTHORIZED

Device ID:
{device_id}

Contact administrator for access.
"""

    print(msg)

    try:
        ctypes.windll.user32.MessageBoxW(0, msg, "VTBC AUTHORIZATION", 0x10)
    except:
        pass

    # OLD ALERT FORMAT (COMMENTED OUT)
    # send_admin_alert(f"UNAUTHORIZED ACCESS ATTEMPT\nUser ID: {user_id}")
    send_admin_alert(f"UNAUTHORIZED ACCESS ATTEMPT\nDevice ID: {device_id}")


# ===== SYSTEM CONTROL =====
system_safe_mode = False


# ===== ALERTING =====
def send_alert(message):

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hostname = socket.gethostname()

    full_msg = f"""
VTBC ALERT

Time: {timestamp}
Host: {hostname}
Version: {__version__}

{message}
"""

    if WINDOWS_ALERT_ENABLED:
        try:
            ctypes.windll.user32.MessageBoxW(0, full_msg, "VTBC ALERT", 0x10)
        except Exception as e:
            print(f"Popup failed: {e}")

    if PUSHOVER_ENABLED:
        try:
            requests.post(
                "https://api.pushover.net/1/messages.json",
                data={
                    "token": PUSHOVER_API_TOKEN,
                    "user": PUSHOVER_USER_KEY,
                    "message": full_msg
                }
            )
        except Exception as e:
            print(f"Pushover failed: {e}")


def send_admin_alert(message):

    if not ADMIN_PUSHOVER_API_TOKEN or not ADMIN_PUSHOVER_USER_KEY:
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hostname = socket.gethostname()

    full_msg = f"""
VTBC ADMIN ALERT

Time: {timestamp}
Host: {hostname}
Version: {__version__}

{message}
"""

    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": ADMIN_PUSHOVER_API_TOKEN,
                "user": ADMIN_PUSHOVER_USER_KEY,
                "message": full_msg
            }
        )
    except Exception as e:
        print(f"Admin alert failed: {e}")


# ===== CREDENTIAL VALIDATION =====
def validate_credentials():

    missing = []

    if not API_KEY or API_KEY == "YOUR_API_KEY":
        missing.append("API_KEY")

    if not REFRESH_TOKEN or REFRESH_TOKEN == "YOUR_REFRESH_TOKEN":
        missing.append("REFRESH_TOKEN")

    if not ACCOUNT_ID:
        missing.append("ACCOUNT_ID")

    if PUSHOVER_ENABLED:

        if not PUSHOVER_USER_KEY or PUSHOVER_USER_KEY == "YOUR_USER_KEY":
            missing.append("PUSHOVER_USER_KEY")

        if not PUSHOVER_API_TOKEN or PUSHOVER_API_TOKEN == "YOUR_API_TOKEN":
            missing.append("PUSHOVER_API_TOKEN")

    if missing:

        msg = f"Missing credentials: {', '.join(missing)}"

        try:
            ctypes.windll.user32.MessageBoxW(0, msg, "VTBC STARTUP FAILURE", 0x10)
        except:
            pass

        raise Exception(msg)


# ===== VALIDATION FLOW =====
def run_system_validation(spx_price=None, send_notifications=False):

    global system_safe_mode

    try:
        ok, msg = check_license(__version__)
        if not ok:
            handle_unauthorized()
            raise Exception(msg)

        # DISABLED PER REQUEST: manifest/build-time validation should not run at runtime.
        # run_build_check()

        # OLD: always dropped safe mode after build/license pass
        # system_safe_mode = False

        # NEW: enforce runtime integrity before clearing safe mode.
        integrity_ok = enforce_runtime_integrity()
        if integrity_ok:
            system_safe_mode = False
        else:
            # keep safe mode ON if checksum fails
            system_safe_mode = True

        log_event(
            "SYSTEM_VALIDATION_PASS" if integrity_ok else "SYSTEM_VALIDATION_FAIL",
            spx_price,
            None,
            None,
            None,
            details=msg if integrity_ok else "Checksum validation failed."
        )

        if send_notifications and integrity_ok:
            send_alert(f"SYSTEM VALIDATION PASSED\n{msg}")

    except Exception as e:

        system_safe_mode = True

        error_msg = f"SYSTEM VALIDATION FAILED\nReason: {str(e)}"

        log_event(
            "SYSTEM_VALIDATION_FAIL",
            spx_price,
            None,
            None,
            None,
            details=error_msg
        )

        print(f"\nSYSTEM IN SAFE MODE: {error_msg}\n")

        if send_notifications:
            send_alert(error_msg)

        send_admin_alert(error_msg)


def get_today_expiry():
    return datetime.now().strftime("%y%m%d")


def select_strike_K(spx_price, atm, direction):
    if direction == "C":
        return atm + STRIKE_STEP if atm < spx_price else atm
    else:
        return atm - STRIKE_STEP if atm > spx_price else atm


# ===== DISTRIBUTION CHECKSUM VERIFICATION HELPER =====
# SURGICAL CHECKSUM VERIFICATION INSERTION
def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_distribution_checksums(checksums_json_path, target_dir, fail_on_mismatch=False):
    """
    Verify checksums.json produced by the build installer against files in target_dir.

    NEW: Changed fail_on_mismatch default to False (optional for development).
    Exits with code 1 on mismatch only if fail_on_mismatch=True.
    """
    if not os.path.exists(checksums_json_path):
        print(f"⚠️  Missing checksums.json: {checksums_json_path}")
        if fail_on_mismatch:
            sys.exit(1)
        return False

    with open(checksums_json_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    ok = True

    support = data.get("support", {})
    if support:
        fname = support.get("file")
        expected = (support.get("sha256") or "").lower()
        path = os.path.join(target_dir, fname)
        if not os.path.exists(path):
            print(f"Missing file: {path}")
            ok = False
        else:
            actual = _sha256(path).lower()
            if actual != expected:
                print(f"Checksum mismatch for {fname}\n expected: {expected}\n actual:   {actual}")
                ok = False

    separate = data.get("separate", {})
    for fname, expected in separate.items():
        expected = (expected or "").lower()
        path = os.path.join(target_dir, fname)
        if not os.path.exists(path):
            print(f"Missing file: {path}")
            ok = False
            continue
        actual = _sha256(path).lower()
        if actual != expected:
            print(f"Checksum mismatch for {fname}\n expected: {expected}\n actual:   {actual}")
            ok = False

    if not ok and fail_on_mismatch:
        print("Checksum verification FAILED. Aborting.")
        sys.exit(1)

    if ok:
        print("✅ All distribution checksums match.")
    return ok


# ===== MAIN =====
if __name__ == "__main__":

    last_validation_date = None
    # NEW: track one runtime integrity check per weekday date at 09:00
    last_integrity_check_date = None

    # SURGICAL CHECKSUM VERIFICATION INSERTION
    # DISABLED PER REQUEST: checksums.json is no longer used.
    # install_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    # checksums_path = os.path.join(install_dir, "checksums.json")
    # verify_distribution_checksums(checksums_path, install_dir, fail_on_mismatch=False)

    # NEW: REQUIRED runtime EXE checksum check at startup (root dir vs cs.json)
    enforce_runtime_integrity()

    validate_credentials()
    run_system_validation(send_notifications=True)

    # OLD EMA INITIALIZATION (COMMENTED OUT)
    # ema_engine = EMAEngine([EMA3_SECONDS, EMA5_SECONDS, EMA20_SECONDS])

    # OLD: client always defaulted to SIM because `live` was never passed (COMMENTED OUT)
    # client = TSClient(API_KEY, REFRESH_TOKEN, ACCOUNT_ID)
    # NEW: route order endpoints by the flag.
    #   ENABLE_LIVE_TRADING = True  -> trades sent to the LIVE trading URL
    #   ENABLE_LIVE_TRADING = False -> the SAME trades sent to the SIM trading URL
    try:
        client = TSClient(API_KEY, REFRESH_TOKEN, ACCOUNT_ID, live=ENABLE_LIVE_TRADING)
    except Exception as e:
        system_safe_mode = True
        error_msg = f"TS CLIENT INIT FAILED\nReason: {str(e)}"
        print(error_msg)
        send_alert(error_msg)
        send_admin_alert(error_msg)
        raise
    state = ExecutionState()

    print("SYSTEM STARTED")

    expiry = get_today_expiry()

    # OLD REBUILD LOGIC (COMMENTED OUT)
    # prices = get_minute_prices_for_rebuild(client, expiry)
    # rebuild_emas(ema_engine, prices)

    # NEW BOOTSTRAP INITIALIZATION
    ema_engine = initialize_ema_engine(client, expiry)

    try:
        while True:

            now = datetime.now()
            time_str = now.strftime("%H:%M:%S")

            today = now.date()

            # DAILY VALIDATION remains
            if now.strftime("%H:%M") == "09:00":
                if last_validation_date != today:
                    print("\n=== DAILY VALIDATION ===")
                    run_system_validation(send_notifications=True)
                    last_validation_date = today

            # NEW: Daily runtime EXE checksum at 09:00 ET, Monday-Friday only
            # weekday(): Monday=0 ... Sunday=6
            if now.weekday() < 5 and now.strftime("%H:%M") == "09:00":
                if last_integrity_check_date != today:
                    print("\n=== DAILY INTEGRITY CHECK (EXE vs cs.json) ===")
                    enforce_runtime_integrity()
                    last_integrity_check_date = today

            # NEW: Check force-exit time
            if FORCE_EXIT_ENABLED and time_str >= FORCE_EXIT_TIME:
                if state.state != State.IDLE:
                    print(f"[{time_str}] FORCE-EXIT TIME REACHED — Canceling position")
                    if state.order_id:
                        try:
                            client.cancel_order(state.order_id)
                            log_event("FORCE_EXIT", None, None, None, None, order_id=state.order_id)
                        except Exception as e:
                            print(f"Failed to cancel order: {e}")
                    state.state = State.IDLE

            allow_entries = not (time_str < TRADE_START_TIME or time_str >= STOP_NEW_ENTRIES)

            spx_data = client.get_spx_price()
            if not spx_data:
                time.sleep(LOOP)
                continue

            spx_price = float(spx_data["Quotes"][0]["Last"])

            surface = get_atm_surface(client, expiry, spx_price)

            ema_engine.update(spx_price, now)

            trade = evaluate_trade(spx_price, surface, ema_engine)

            # NEW: Handle long entry state
            if state.state == State.LONG_WORKING:
                # Poll order status (simplified: just check if still working)
                try:
                    order_status = client.get_order(state.order_id)
                    status = order_status.get("OrderStatus", "UNKNOWN")

                    check_result = state.check_long(status)

                    if check_result == "FILLED":
                        print(f"[{time_str}] Order FILLED: {state.order_id}")
                        filled_direction = state.direction
                        filled_long_strike = state.long_strike
                        filled_short_strike = state.short_strike

                        state.add_position(filled_direction, filled_long_strike, filled_short_strike)
                        # Log entry long strike as the primary filled strike for this vertical.
                        log_event("ORDER_FILLED", spx_price, filled_direction, filled_long_strike, None, order_id=state.order_id)
                        state.state = State.IDLE
                    elif check_result == "CANCEL":
                        print(f"[{time_str}] Order TIMEOUT — Canceling: {state.order_id}")
                        try:
                            client.cancel_order(state.order_id)
                        except Exception as e:
                            print(f"Cancel failed: {e}")
                        state.state = State.IDLE
                        log_event("ORDER_TIMEOUT", spx_price, state.direction, state.short_strike, None, order_id=state.order_id)
                except Exception as e:
                    print(f"Error checking order status: {e}")

            # Entry conditions with full qualification + 2-leg vertical order
            if (
                trade
                and state.state == State.IDLE
                and allow_entries
                # OLD: ENABLE_LIVE_TRADING blocked the trade entirely when False (COMMENTED OUT)
                # and ENABLE_LIVE_TRADING
                # NEW: trades are ALWAYS placed when qualified; ENABLE_LIVE_TRADING only
                # selects the destination URL (LIVE vs SIM) via TSClient(live=...) above.
                and not system_safe_mode
            ):

                direction = trade["direction"]
                atm = surface["atm"]
                long_strike = select_strike_K(spx_price, atm, direction)

                if direction == "C":
                    short_strike = long_strike + SPREAD_WIDTH
                else:
                    short_strike = long_strike - SPREAD_WIDTH

                # Qualification 0: expected directional move using ATM single-leg option mid
                atm_option = get_option_quote(client, expiry, atm, direction)
                if not atm_option or not check_min_em(atm_option["mid"], MIN_EM):
                    time.sleep(LOOP)
                    continue

                # Qualification 1: active per-direction cap
                if direction == "C" and state.count_active("C") >= MAX_CALLS_ACTIVE:
                    time.sleep(LOOP)
                    continue
                if direction == "P" and state.count_active("P") >= MAX_PUTS_ACTIVE:
                    time.sleep(LOOP)
                    continue

                # Qualification 2: conflict detection
                # trade_conflicts.has_conflict expects proposed_strikes as (pL1, pS, pL2).
                if direction == "C":
                    # Calls: lower long, center short, upper wing.
                    proposed = (long_strike, short_strike, short_strike + SPREAD_WIDTH)
                else:
                    # Puts: lower wing, center short, upper long.
                    proposed = (short_strike - SPREAD_WIDTH, short_strike, long_strike)

                if has_conflict(state.get_active_positions(), direction, proposed, SPREAD_WIDTH):
                    time.sleep(LOOP)
                    continue

                # Qualification 3 + 4: OTM vertical spread bid/ask width + premium cap
                spread_quote = get_spread_quote(client, expiry, long_strike, short_strike, direction)
                if not spread_quote:
                    time.sleep(LOOP)
                    continue

                bid_ask_width = spread_quote["ask"] - spread_quote["bid"]
                if bid_ask_width >= BID_ASK_SPREAD:
                    time.sleep(LOOP)
                    continue

                mid = spread_quote["mid"]
                if mid <= 0:
                    time.sleep(LOOP)
                    continue

                # MAX_PREMIUM is in cents (e.g., 200 = $2.00/share); SLIPPAGE is in dollars/share.
                premium_cap = (MAX_PREMIUM / 100) + SLIPPAGE
                # Strictly less than cap per strategy rule.
                if mid >= premium_cap:
                    time.sleep(LOOP)
                    continue

                # Quantity sizing
                if POSITIONS >= 1:
                    quantity = int(POSITIONS)
                else:
                    # mid = dollars/share, ACCOUNT_CAPITAL = dollars.
                    contract_multiplier = 100  # shares/contract
                    base_contracts = math.floor(ACCOUNT_CAPITAL / (mid * contract_multiplier))
                    quantity = max(1, int(POSITIONS * base_contracts))

                # Limit price
                limit_price = round(min(mid + SLIPPAGE, premium_cap), 2)

                order_payload = build_vertical_order(
                    expiry=expiry,
                    long_strike=long_strike,
                    short_strike=short_strike,
                    right=direction,
                    quantity=quantity,
                    limit_price=limit_price
                )
                order_payload["AccountID"] = ACCOUNT_ID

                oid = client.place_order(order_payload)

                if oid:
                    state.submit_long(oid, long_strike, short_strike, quantity, direction, limit_price)

                    log_event(
                        "ENTRY_PLACED",
                        spx_price,
                        direction,
                        long_strike,
                        SPREAD_WIDTH,
                        order_id=oid
                    )

            time.sleep(LOOP)

    finally:
        try:
            save_ema_state(ema_engine)
        except Exception as e:
            print(f"Failed to save EMA state: {e}")