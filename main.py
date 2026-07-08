# main.py
# NEW: Device-ID auth + EXE checksum enforcement (startup + 09:00 ET M-F)
__version__ = "1.4.4"
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
# OBSOLETE PER REQUEST: runtime merged config loading disabled; config.py is single source of truth.
# try:
#     from config_loader import load_merged_config
# except Exception:
#     load_merged_config = None

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
from datetime import datetime, timedelta

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

# OBSOLETE PER REQUEST: merged config extras disabled.
# # NEW: Load PROFIT_MULTIPLIER and retry config from merged config
# # Falls back to defaults if config_loader is unavailable or key is absent.
# try:
#     _merged_cfg = load_merged_config() if load_merged_config else {}
#     PROFIT_MULTIPLIER = _merged_cfg.get("PROFIT_MULTIPLIER", 1.2)
#     ORDER_RETRY_ATTEMPTS = _merged_cfg.get("ORDER_RETRY_ATTEMPTS", 3)
#     TOKEN_REFRESH_DELAY = _merged_cfg.get("TOKEN_REFRESH_DELAY", 1)
# except Exception:
#     PROFIT_MULTIPLIER = 1.2
#     ORDER_RETRY_ATTEMPTS = 3
#     TOKEN_REFRESH_DELAY = 1

# UPDATED PER REQUEST: read directly from config.py (_cfg) with safe fallbacks.
PROFIT_MULTIPLIER = getattr(_cfg, "PROFIT_MULTIPLIER", 1.2)
ORDER_RETRY_ATTEMPTS = getattr(_cfg, "ORDER_RETRY_ATTEMPTS", 3)
TOKEN_REFRESH_DELAY = getattr(_cfg, "TOKEN_REFRESH_DELAY", 1)

# NEW: configurable EMA rebuild/bootstrapping depth (default 120)
EMA_REBUILD_DEPTH = getattr(_cfg, "EMA_REBUILD_DEPTH", 120)

from ts_client import TSClient
from execution_state import ExecutionState, State
from order_builder import build_vertical_order, build_conversion_order
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


class SymbolProbeError(RuntimeError):  #1
    pass  #1


def choose_direction_symbol(client, candidates=None):  #1
    if candidates is None:  #1
        candidates = ["SPX", "$SPX", "^SPX", ".SPX", "SPX.X"]  #1
    for sym in candidates:  #1
        try:  #1
            r = client._req(  #1
                method=requests.get,  #1
                url=f"{client.base_url}/marketdata/quotes/{sym}"  #1
            )  #1
            if r and isinstance(r, dict) and "Quotes" in r:  #1
                print(f"[SymbolProbe] Accepted symbol: {sym}")  #1
                return sym  #1
            print(f"[SymbolProbe] Rejected symbol: {sym} (no Quotes key)")  #1
        except Exception as e:  #1
            print(f"[SymbolProbe] Rejected symbol: {sym} ({e})")  #1
    raise SymbolProbeError(f"No valid direction symbol found. Tried: {candidates}")  #1


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


# ===== FATAL EXIT =====
def fatal_exit(reason, alert_user=True, alert_admin=True):
    """
    Hard stop for any unrecoverable condition.
    1. Prints reason to console.
    2. Sends Pushover alert to user and admin (if configured).
    3. Shows a Windows message box.
    4. Waits for any key before exiting so the user can read the console.
    Never returns — always calls sys.exit(1).
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hostname = socket.gethostname()

    full_msg = (
        f"VTBC FATAL ERROR\n\n"
        f"Time: {timestamp}\n"
        f"Host: {hostname}\n"
        f"Version: {__version__}\n\n"
        f"{reason}"
    )

    print(f"\n{'='*60}")
    print(full_msg)
    print(f"{'='*60}\n")

    if alert_user:
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
                print(f"Pushover alert failed: {e}")

        # Windows message box — blocks until user clicks OK
        try:
            ctypes.windll.user32.MessageBoxW(0, full_msg, "VTBC FATAL ERROR", 0x10)
        except Exception as e:
            print(f"Message box failed: {e}")

    if alert_admin:
        try:
            if ADMIN_PUSHOVER_API_TOKEN and ADMIN_PUSHOVER_USER_KEY:
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

    # Wait for keypress so user can read the console before the window closes
    print("Press any key to exit...")
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.getch()
        else:
            input()
    except Exception:
        pass

    sys.exit(1)


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

    # CLIENT_SECRET required for TradeStation OAuth
    client_secret = getattr(_cfg, "CLIENT_SECRET", None)
    if not client_secret or client_secret == "YOUR_CLIENT_SECRET":
        missing.append("CLIENT_SECRET")

    if not ACCOUNT_ID:
        missing.append("ACCOUNT_ID")

    if PUSHOVER_ENABLED:

        if not PUSHOVER_USER_KEY or PUSHOVER_USER_KEY == "YOUR_USER_KEY":
            missing.append("PUSHOVER_USER_KEY")

        if not PUSHOVER_API_TOKEN or PUSHOVER_API_TOKEN == "YOUR_API_TOKEN":
            missing.append("PUSHOVER_API_TOKEN")

    if missing:
        fatal_exit(f"MISSING CREDENTIALS\n{', '.join(missing)}")


# ===== VALIDATION FLOW =====
def run_system_validation(spx_price=None, send_notifications=False):
    """
    Runs license check and runtime integrity check.
    Any failure calls fatal_exit() — the process terminates and
    waits for the user to acknowledge.
    """
    # License check
    ok, msg = check_license(__version__)
    if not ok:
        handle_unauthorized()
        try:
            log_event("SYSTEM_VALIDATION_FAIL", spx_price, None, None, None,
                      details=f"License check failed: {msg}")
        except Exception:
            pass
        fatal_exit(f"LICENSE VALIDATION FAILED\n{msg}")

    # DISABLED PER REQUEST: manifest/build-time validation should not run at runtime.
    # run_build_check()

    # OBSOLETE PER REQUEST: runtime EXE integrity check removed from run_system_validation()
    # to avoid duplicate startup checksum execution.
    # Runtime integrity is enforced at:
    # 1) startup before run_system_validation(), and
    # 2) daily 09:00 weekday check in main loop.
    # integrity_ok, failing_exe, reason = verify_runtime_exe_checksums()
    # if not integrity_ok:
    #     user_msg = f"Data corruption in {failing_exe}.  Trading suspended"
    #     device_id = get_device_id()
    #     admin_msg = f"{user_msg}\nCorruption found on computer '{device_id}'"
    #     try:
    #         log_event("SYSTEM_VALIDATION_FAIL", spx_price, None, None, None, details=reason)
    #     except Exception:
    #         pass
    #     send_admin_alert(admin_msg)
    #     fatal_exit(user_msg)

    # All checks passed
    try:
        log_event("SYSTEM_VALIDATION_PASS", spx_price, None, None, None, details=msg)
    except Exception:
        pass

    if send_notifications:
        send_alert(f"SYSTEM VALIDATION PASSED\n{msg}")


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


# ===== FORCE EXIT HELPERS =====

def _parse_force_exit_thresholds():
    """
    Parse FORCE_EXIT_TIME at runtime (re-read from _cfg each call so intraday
    config changes are respected) and return the three datetime thresholds for
    today: T+0 (100%), T+15 (50%), T+30 (10%).
    """
    fet = _cfg.FORCE_EXIT_TIME          # e.g. "14:45:00"
    today = datetime.now().date()
    t0 = datetime.strptime(f"{today} {fet}", "%Y-%m-%d %H:%M:%S")
    return t0, t0 + timedelta(minutes=15), t0 + timedelta(minutes=30)


def _place_force_exit_conversion(client, pos, limit_price, spx_price, label, time_str):
    """
    Cancel any existing conversion order on this position, then place a new
    short vertical spread (conversion) order at limit_price with retry logic.
    Updates pos["conversion_order"] in place.
    Returns True if order was successfully placed, False otherwise.
    """
    # Cancel existing conversion order for this position if one is open
    existing = pos.get("conversion_order")
    if existing and existing.get("order_id"):
        try:
            client.cancel_order(existing["order_id"])
            print(f"[{time_str}] [{label}] Canceled prior conversion order: {existing['order_id']}")
            log_event(
                "FORCE_EXIT_CANCEL",
                spx_price,
                pos["direction"],
                pos["short_strike"],
                SPREAD_WIDTH,
                order_id=existing["order_id"]
            )
        except Exception as e:
            print(f"[{time_str}] [{label}] Cancel of prior conversion order failed: {e}")

    # Build the conversion (short vertical) order payload
    direction = pos["direction"]
    short_strike = pos["short_strike"]
    qty = pos["qty"]

    if direction == "C":
        far_strike = short_strike + SPREAD_WIDTH
    else:
        far_strike = short_strike - SPREAD_WIDTH

    conversion_payload = build_conversion_order(
        expiry=get_today_expiry(),
        short_strike=short_strike,
        far_strike=far_strike,
        right=direction,
        quantity=qty,
        limit_price=limit_price
    )
    conversion_payload["AccountID"] = ACCOUNT_ID

    # Retry loop
    conv_oid = None
    last_error = None
    for attempt in range(1, ORDER_RETRY_ATTEMPTS + 1):
        try:
            conv_oid = client.place_order(conversion_payload)
            if conv_oid:
                break
            print(f"[{time_str}] [{label}] Conversion attempt {attempt}: no order ID returned")
        except Exception as e:
            last_error = e
            print(f"[{time_str}] [{label}] Conversion attempt {attempt} failed: {e}")
            if attempt < ORDER_RETRY_ATTEMPTS:
                time.sleep(TOKEN_REFRESH_DELAY)

    if conv_oid:
        print(f"[{time_str}] [{label}] Force-exit conversion placed: {conv_oid} @ {limit_price}")
        pos["conversion_order"] = {
            "order_id": conv_oid,
            "limit_price": limit_price,
            "stage": label
        }
        log_event(
            f"FORCE_EXIT_{label}",
            spx_price,
            direction,
            short_strike,
            SPREAD_WIDTH,
            order_id=conv_oid
        )
        return True
    else:
        err_detail = str(last_error) if last_error else "no order ID returned"
        print(f"[{time_str}] [{label}] Force-exit conversion FAILED after {ORDER_RETRY_ATTEMPTS} attempts: {err_detail}")
        send_admin_alert(
            f"FORCE EXIT CONVERSION FAILED [{label}]\n"
            f"Direction: {direction}\n"
            f"Short Strike: {short_strike}\n"
            f"Far Strike: {far_strike}\n"
            f"Limit: {limit_price}\n"
            f"Attempts: {ORDER_RETRY_ATTEMPTS}\n"
            f"Error: {err_detail}"
        )
        log_event(
            f"FORCE_EXIT_{label}_FAILED",
            spx_price,
            direction,
            short_strike,
            SPREAD_WIDTH
        )
        pos["conversion_order"] = None
        return False


def handle_force_exit(client, state, now, spx_price):
    """
    Called every loop tick when FORCE_EXIT_ENABLED and now >= t0.

    Stage logic (evaluated per active position independently):
      T+0  (FORCE_EXIT_TIME)      : cancel any working LONG_WORKING order;
                                    cancel any working CONVERSION order;
                                    place conversion at 100% of entry_price.
      T+15 (FORCE_EXIT_TIME+15m)  : cancel unfilled conversion; re-place at 50%.
      T+30 (FORCE_EXIT_TIME+30m)  : cancel unfilled conversion; re-place at 10%.
      After T+30                  : no further action — let expire worthless.

    Each position tracks which stage it has reached via
    pos["conversion_order"]["stage"] to avoid re-submitting on every tick.
    """
    time_str = now.strftime("%H:%M:%S")
    t0, t15, t30 = _parse_force_exit_thresholds()

    # --- Cancel any unfilled working LONG entry order at T+0 ---
    if state.state == State.LONG_WORKING:
        if state.order_id:
            try:
                client.cancel_order(state.order_id)
                log_event("FORCE_EXIT_LONG_CANCEL", spx_price, state.direction,
                          state.short_strike, None, order_id=state.order_id)
                print(f"[{time_str}] FORCE-EXIT: Canceled unfilled long entry order: {state.order_id}")
            except Exception as e:
                print(f"[{time_str}] FORCE-EXIT: Failed to cancel long entry order: {e}")
        state.state = State.IDLE

    # --- Cancel any unfilled working CONVERSION order at T+0
    #     (the normal profit-target conversion, not a force-exit one) ---
    if state.state == State.CONVERSION_WORKING:
        if state.order_id:
            try:
                client.cancel_order(state.order_id)
                log_event("FORCE_EXIT_CONV_CANCEL", spx_price, state.direction,
                          state.short_strike, None, order_id=state.order_id)
                print(f"[{time_str}] FORCE-EXIT: Canceled unfilled conversion order: {state.order_id}")
            except Exception as e:
                print(f"[{time_str}] FORCE-EXIT: Failed to cancel conversion order: {e}")
        state.state = State.IDLE

    # --- Process each active filled position independently ---
    for pos in state.active_positions:
        entry_price = pos["entry_price"]
        direction = pos["direction"]
        short_strike = pos["short_strike"]
        conv = pos.get("conversion_order")
        current_stage = conv.get("stage") if conv else None

        # Check if an existing conversion order for this position has filled
        if conv and conv.get("order_id"):
            try:
                order_status = client.get_order(conv["order_id"])
                status = order_status.get("OrderStatus", "UNKNOWN")
                if status == "FILLED":
                    print(f"[{time_str}] FORCE-EXIT: Conversion FILLED for {direction} {short_strike}: {conv['order_id']}")
                    log_event(
                        f"FORCE_EXIT_{current_stage}_FILLED",
                        spx_price,
                        direction,
                        short_strike,
                        SPREAD_WIDTH,
                        order_id=conv["order_id"]
                    )
                    pos["conversion_order"] = {"order_id": None, "stage": "DONE"}
                    continue  # this position is closed — nothing more to do
            except Exception as e:
                print(f"[{time_str}] FORCE-EXIT: Error checking conversion status for {direction} {short_strike}: {e}")

        # Skip positions already closed or at final stage
        if current_stage == "DONE":
            continue
        if current_stage == "T30":
            # Final stage already placed — let it ride or expire
            continue

        # Determine which stage applies right now and whether we need to act
        if now >= t30:
            if current_stage != "T30":
                limit_price = round(entry_price * 0.10, 2)
                _place_force_exit_conversion(client, pos, limit_price, spx_price, "T30", time_str)

        elif now >= t15:
            if current_stage != "T15":
                limit_price = round(entry_price * 0.50, 2)
                _place_force_exit_conversion(client, pos, limit_price, spx_price, "T15", time_str)

        elif now >= t0:
            if current_stage != "T0":
                limit_price = round(entry_price * 1.00, 2)
                _place_force_exit_conversion(client, pos, limit_price, spx_price, "T0", time_str)


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
    ok, failing_exe, reason = verify_runtime_exe_checksums()
    if not ok:
        device_id = get_device_id()
        fatal_exit(
            f"Data corruption in {failing_exe}.  Trading suspended\n"
            f"Corruption found on computer '{device_id}'\n"
            f"Detail: {reason}"
        )

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
        fatal_exit(f"TS CLIENT INIT FAILED\n{str(e)}")

    state = ExecutionState()
    print("SYSTEM STARTED")
    # NEW: loop debug cadence
    debug_loop_counter = 0
    DEBUG_EVERY_N_LOOPS = 1  # VTBC_DEBUG_TAG: TEMP high-visibility, set back to 30 after debugging

    expiry = get_today_expiry()

    # OLD TEST/PROBE SYMBOL LOGIC (COMMENTED OUT) #1
    # direction_symbol = "SPX"  #1
    # try:  #1
    #     direction_symbol = choose_direction_symbol(client)  #1
    #     print(f"[INIT] Direction symbol resolved to: {direction_symbol}")  #1
    # except SymbolProbeError as e:  #1
    #     print(f"[INIT] Symbol probe failed, defaulting to SPX: {e}")  #1

    # NEW: fixed production symbols per TradeStation
    direction_symbol = "$SPX.X"
    weekly_options_symbol = "$SPXW.X"  # reserved for weekly options data path

    # OLD REBUILD LOGIC (COMMENTED OUT)
    # prices = get_minute_prices_for_rebuild(client, expiry)
    # rebuild_emas(ema_engine, prices)

    # NEW BOOTSTRAP INITIALIZATION
    # ema_engine = initialize_ema_engine(client, expiry, direction_symbol)  #2
    # UPDATED PER REQUEST: pass configurable EMA_REBUILD_DEPTH (default 120)
    print(f"[BOOTSTRAP] Initializing EMA engine (symbol={direction_symbol}, depth={EMA_REBUILD_DEPTH})")
    ema_engine = initialize_ema_engine(client, expiry, direction_symbol, EMA_REBUILD_DEPTH)
    print("[BOOTSTRAP] EMA engine initialized successfully")
    print("[MAIN] Entering main trading loop")

    try:
        while True:

            now = datetime.now()
            time_str = now.strftime("%H:%M:%S")
            # VTBC_DEBUG_TAG
            print(f"[VTBC_DEBUG_TAG][LOOP_START] t={time_str} state={state.state}")

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
                    ok, failing_exe, reason = verify_runtime_exe_checksums()
                    if not ok:
                        device_id = get_device_id()
                        fatal_exit(
                            f"Data corruption in {failing_exe}.  Trading suspended\n"
                            f"Corruption found on computer '{device_id}'\n"
                            f"Detail: {reason}"
                        )
                    last_integrity_check_date = today

            # ===== FORCE EXIT =====
            # Replaces the old single-order cancel stub.
            # Handles all active positions independently across T+0, T+15, T+30 stages.
            if FORCE_EXIT_ENABLED:
                t0, _, _ = _parse_force_exit_thresholds()
                if now >= t0:
                    # VTBC_DEBUG_TAG
                    print(f"[VTBC_DEBUG_TAG][FORCE_EXIT] running handle_force_exit at {time_str}")
                    handle_force_exit(client, state, now, spx_price if 'spx_price' in dir() else None)

            allow_entries = not (time_str < TRADE_START_TIME or time_str >= STOP_NEW_ENTRIES)

            # OLD TEST SYMBOL FETCH (COMMENTED OUT) #2
            # spx_data = client.get_quotes([direction_symbol])  #2
            # if not spx_data or "Quotes" not in spx_data or not spx_data["Quotes"]:  #2

            # VTBC_DEBUG_TAG: hard timeout at call site
            print(f"[VTBC_DEBUG_TAG][QUOTE_REQ] requesting {direction_symbol} timeout=(2.0, 3.0)")
            spx_data = client.get_quotes([direction_symbol], timeout=(2.0, 3.0))
            if not spx_data or "Quotes" not in spx_data or not spx_data["Quotes"]:
                print(f"[DATA] No index quote returned for {direction_symbol} at {time_str}")
                # VTBC_DEBUG_TAG
                print(f"[VTBC_DEBUG_TAG][QUOTE_EMPTY] skipping loop at {time_str}")
                time.sleep(LOOP)
                continue

            try:
                # OLD TEST PRICE PARSE (COMMENTED OUT) #2
                # spx_price = float(spx_data["Quotes"][0]["Last"])  #2
                spx_price = float(spx_data["Quotes"][0]["Last"])
                # VTBC_DEBUG_TAG
                print(f"[VTBC_DEBUG_TAG][SPX_LAST] t={time_str} {direction_symbol} last={spx_price}")
            except Exception as e:
                print(f"[DATA] Failed to parse {direction_symbol} Last at {time_str}: {e}")
                time.sleep(LOOP)
                continue

            # VTBC_DEBUG_TAG
            print(f"[VTBC_DEBUG_TAG][ATM_SURFACE] requesting ATM surface expiry={expiry} spx={spx_price}")
            surface = get_atm_surface(client, expiry, spx_price)
            if not surface or "atm" not in surface:
                print(f"[VTBC_DEBUG_TAG][ATM_SURFACE_FAIL] invalid surface={surface}")
                time.sleep(LOOP)
                continue

            ema_engine.update(spx_price, now)

            trade = evaluate_trade(spx_price, surface, ema_engine)
            # NEW: periodic runtime visibility
            debug_loop_counter += 1
            if debug_loop_counter % DEBUG_EVERY_N_LOOPS == 0:
                try:
                    ema3_dbg = ema_engine.values.get(EMA3_SECONDS)
                    ema5_dbg = ema_engine.values.get(EMA5_SECONDS)
                    ema20_dbg = ema_engine.values.get(EMA20_SECONDS)
                except Exception:
                    ema3_dbg = None
                    ema5_dbg = None
                    ema20_dbg = None

                trade_dir_dbg = trade.get("direction") if isinstance(trade, dict) else None

                print(
                    f"[LOOP DEBUG] t={time_str} "
                    f"spx={spx_price} "
                    f"ema3={ema3_dbg} ema5={ema5_dbg} ema20={ema20_dbg} "
                    f"trade={trade_dir_dbg} "
                    f"state={state.state} "
                    f"allow_entries={allow_entries} "
                    f"window={TRADE_START_TIME}->{STOP_NEW_ENTRIES}"
                )

            # NEW: explicit no-trade visibility
            if (not trade) and (debug_loop_counter % DEBUG_EVERY_N_LOOPS == 0):
                print(
                    f"[REJECT SIGNAL] No directional signal "
                    f"(trade=None) at {time_str} spx={spx_price}"
                )

            # NEW: explicit gating visibility before entry block
            if trade and state.state != State.IDLE and (debug_loop_counter % DEBUG_EVERY_N_LOOPS == 0):
                print(f"[REJECT GATE] state not IDLE (state={state.state})")
            if trade and state.state == State.IDLE and not allow_entries and (debug_loop_counter % DEBUG_EVERY_N_LOOPS == 0):
                print(
                    f"[REJECT GATE] outside entry window now={time_str} "
                    f"window={TRADE_START_TIME}->{STOP_NEW_ENTRIES}"
                )

            # Handle long entry order: poll for fill or timeout
            if state.state == State.LONG_WORKING:
                # VTBC_DEBUG_TAG
                print(f"[VTBC_DEBUG_TAG][LONG_WORKING] polling order_id={state.order_id}")
                try:
                    order_status = client.get_order(state.order_id)
                    status = order_status.get("OrderStatus", "UNKNOWN")

                    check_result = state.check_long(status)

                    if check_result == "FILLED":
                        print(f"[{time_str}] Long order FILLED: {state.order_id}")
                        filled_direction = state.direction
                        filled_long_strike = state.long_strike
                        filled_short_strike = state.short_strike
                        filled_qty = state.qty
                        filled_entry_price = state.entry_price

                        # entry_price and qty now stored per-position for force-exit pricing
                        state.add_position(
                            filled_direction,
                            filled_long_strike,
                            filled_short_strike,
                            filled_entry_price,
                            filled_qty
                        )
                        log_event("ORDER_FILLED", spx_price, filled_direction, filled_long_strike, None, order_id=state.order_id)

                        # Place conversion order to complete the butterfly.
                        # Sells the shared short strike and buys a far wing at
                        # a credit of PROFIT_MULTIPLIER * premium paid for the long vertical.
                        if filled_direction == "C":
                            far_strike = filled_short_strike + SPREAD_WIDTH
                        else:
                            far_strike = filled_short_strike - SPREAD_WIDTH

                        conversion_limit = round(filled_entry_price * PROFIT_MULTIPLIER, 2)

                        conversion_payload = build_conversion_order(
                            expiry=expiry,
                            short_strike=filled_short_strike,
                            far_strike=far_strike,
                            right=filled_direction,
                            quantity=filled_qty,
                            limit_price=conversion_limit
                        )
                        conversion_payload["AccountID"] = ACCOUNT_ID

                        # Retry loop: attempt up to ORDER_RETRY_ATTEMPTS times on API exception.
                        conv_oid = None
                        last_conv_error = None
                        for attempt in range(1, ORDER_RETRY_ATTEMPTS + 1):
                            try:
                                conv_oid = client.place_order(conversion_payload)
                                if conv_oid:
                                    break  # success — exit retry loop
                                print(f"[{time_str}] Conversion order attempt {attempt}: no order ID returned")
                            except Exception as e:
                                last_conv_error = e
                                print(f"[{time_str}] Conversion order attempt {attempt} failed: {e}")
                                if attempt < ORDER_RETRY_ATTEMPTS:
                                    time.sleep(TOKEN_REFRESH_DELAY)

                        if conv_oid:
                            print(f"[{time_str}] Conversion order placed: {conv_oid} @ {conversion_limit}")
                            state.submit_conversion(conv_oid)
                            log_event(
                                "CONVERSION_PLACED",
                                spx_price,
                                filled_direction,
                                filled_short_strike,
                                SPREAD_WIDTH,
                                order_id=conv_oid
                            )
                        else:
                            err_detail = str(last_conv_error) if last_conv_error else "no order ID returned"
                            print(f"[{time_str}] Conversion order FAILED after {ORDER_RETRY_ATTEMPTS} attempts: {err_detail} — reverting to IDLE")
                            send_admin_alert(
                                f"CONVERSION ORDER FAILED\n"
                                f"Direction: {filled_direction}\n"
                                f"Short Strike: {filled_short_strike}\n"
                                f"Far Strike: {far_strike}\n"
                                f"Limit: {conversion_limit}\n"
                                f"Attempts: {ORDER_RETRY_ATTEMPTS}\n"
                                f"Error: {err_detail}"
                            )
                            log_event(
                                "CONVERSION_FAILED",
                                spx_price,
                                filled_direction,
                                filled_short_strike,
                                SPREAD_WIDTH
                            )
                            state.state = State.IDLE

                    elif check_result == "CANCEL":
                        print(f"[{time_str}] Long order TIMEOUT — Canceling: {state.order_id}")
                        try:
                            client.cancel_order(state.order_id)
                        except Exception as e:
                            print(f"Cancel failed: {e}")
                        state.state = State.IDLE
                        log_event("ORDER_TIMEOUT", spx_price, state.direction, state.short_strike, None, order_id=state.order_id)

                except Exception as e:
                    print(f"Error checking long order status: {e}")

            # Handle conversion order: poll for fill or timeout
            if state.state == State.CONVERSION_WORKING:
                # VTBC_DEBUG_TAG
                print(f"[VTBC_DEBUG_TAG][CONV_WORKING] polling order_id={state.order_id}")
                try:
                    order_status = client.get_order(state.order_id)
                    status = order_status.get("OrderStatus", "UNKNOWN")

                    check_result = state.check_conversion(status)

                    if check_result == "DONE":
                        print(f"[{time_str}] Conversion order FILLED: {state.order_id}")
                        log_event(
                            "CONVERSION_FILLED",
                            spx_price,
                            state.direction,
                            state.short_strike,
                            SPREAD_WIDTH,
                            order_id=state.order_id
                        )
                        state.state = State.IDLE

                    elif datetime.now() >= state.deadline:
                        print(f"[{time_str}] Conversion order TIMEOUT — Canceling: {state.order_id}")
                        try:
                            client.cancel_order(state.order_id)
                        except Exception as e:
                            print(f"Conversion cancel failed: {e}")
                        log_event(
                            "CONVERSION_TIMEOUT",
                            spx_price,
                            state.direction,
                            state.short_strike,
                            SPREAD_WIDTH,
                            order_id=state.order_id
                        )
                        state.state = State.IDLE

                except Exception as e:
                    print(f"Error checking conversion order status: {e}")

            # Entry conditions with full qualification + 2-leg vertical order
            if (
                trade
                and state.state == State.IDLE
                and allow_entries
                # OLD: ENABLE_LIVE_TRADING blocked the trade entirely when False (COMMENTED OUT)
                # and ENABLE_LIVE_TRADING
                # NEW: trades are ALWAYS placed when qualified; ENABLE_LIVE_TRADING only
                # selects the destination URL (LIVE vs SIM) via TSClient(live=...) above.
            ):

                direction = trade["direction"]
                atm = surface["atm"]
                long_strike = select_strike_K(spx_price, atm, direction)

                if direction == "C":
                    short_strike = long_strike + SPREAD_WIDTH
                else:
                    short_strike = long_strike - SPREAD_WIDTH

                # NEW: entry attempt breadcrumb
                print(
                    f"[ENTRY CHECK] t={time_str} dir={direction} spx={spx_price} "
                    f"atm={atm} long={long_strike} short={short_strike} expiry={expiry}"
                )

                # Qualification 0: expected directional move using ATM single-leg option mid
                atm_option = get_option_quote(client, expiry, atm, direction)
                if not atm_option:
                    print(
                        f"[REJECT Q0] No ATM option quote "
                        f"(dir={direction} expiry={expiry} atm={atm})"
                    )
                    time.sleep(LOOP)
                    continue

                if not check_min_em(atm_option["mid"], MIN_EM):
                    print(
                        f"[REJECT Q0] EM below threshold "
                        f"(mid={atm_option['mid']} MIN_EM={MIN_EM})"
                    )
                    time.sleep(LOOP)
                    continue

                # Qualification 1: active per-direction cap
                if direction == "C" and state.count_active("C") >= MAX_CALLS_ACTIVE:
                    print(
                        f"[REJECT Q1] Max active CALLS reached "
                        f"({state.count_active('C')}/{MAX_CALLS_ACTIVE})"
                    )
                    time.sleep(LOOP)
                    continue
                if direction == "P" and state.count_active("P") >= MAX_PUTS_ACTIVE:
                    print(
                        f"[REJECT Q1] Max active PUTS reached "
                        f"({state.count_active('P')}/{MAX_PUTS_ACTIVE})"
                    )
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
                    print(
                        f"[REJECT Q2] Strike conflict "
                        f"(dir={direction} proposed={proposed} width={SPREAD_WIDTH})"
                    )
                    time.sleep(LOOP)
                    continue

                # Qualification 3 + 4: OTM vertical spread bid/ask width + premium cap
                spread_quote = get_spread_quote(client, expiry, long_strike, short_strike, direction)
                if not spread_quote:
                    print(
                        f"[REJECT Q3] No spread quote "
                        f"(dir={direction} expiry={expiry} long={long_strike} short={short_strike})"
                    )
                    time.sleep(LOOP)
                    continue

                bid_ask_width = spread_quote["ask"] - spread_quote["bid"]
                if bid_ask_width >= BID_ASK_SPREAD:
                    print(
                        f"[REJECT Q3] Bid/ask width too wide "
                        f"(width={bid_ask_width} threshold={BID_ASK_SPREAD})"
                    )
                    time.sleep(LOOP)
                    continue

                mid = spread_quote["mid"]
                if mid <= 0:
                    print(f"[REJECT Q4] Invalid spread mid (mid={mid})")
                    time.sleep(LOOP)
                    continue

                # OBSOLETE PER REQUEST:
                # MAX_PREMIUM is in cents (e.g., 200 = $2.00/share).
                # Calls: cap = (MAX_PREMIUM / 100) + SLIPPAGE  (buying, slippage adds to cost)
                # Puts:  cap = (MAX_PREMIUM / 100) - SLIPPAGE  (selling premium, slippage reduces proceeds)
                # if direction == "C":
                #     premium_cap = (MAX_PREMIUM / 100) + SLIPPAGE
                # else:
                #     premium_cap = (MAX_PREMIUM / 100) - SLIPPAGE
                #
                # # Strictly less than cap per strategy rule.
                # if mid >= premium_cap:
                #     time.sleep(LOOP)
                #     continue

                # UPDATED PER REQUEST:
                # Spread mid + SLIPPAGE < MAX_PREMIUM/100 for both calls and puts.
                premium_cap = (MAX_PREMIUM / 100)
                if (mid + SLIPPAGE) >= premium_cap:
                    print(
                        f"[REJECT Q4] Premium cap fail "
                        f"(mid={mid} slippage={SLIPPAGE} cap={premium_cap})"
                    )
                    time.sleep(LOOP)
                    continue

                # Quantity sizing
                if POSITIONS >= 1:
                    # Fixed contract count
                    quantity = int(POSITIONS)
                else:
                    # Fractional: RoundDown(ACCOUNT_CAPITAL * POSITIONS / (mid * 100)), minimum 1
                    quantity = max(1, math.floor(ACCOUNT_CAPITAL * POSITIONS / (mid * 100)))

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

                print(
                    f"[ENTRY PASS] placing vertical order "
                    f"(dir={direction} qty={quantity} long={long_strike} short={short_strike} "
                    f"mid={mid} limit={limit_price})"
                )

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
                else:
                    print("[ENTRY FAIL] place_order returned no order ID")

            # VTBC_DEBUG_TAG
            print(f"[VTBC_DEBUG_TAG][LOOP_SLEEP] sleeping {LOOP}s")
            time.sleep(LOOP)


    finally:
        try:
            save_ema_state(ema_engine)
        except Exception as e:
            print(f"Failed to save EMA state: {e}")