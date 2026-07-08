__version__ = "2.0.5"
# copyright (c) Gregory Howard 2026   all rights reserved

import tkinter as tk
from tkinter import ttk, messagebox
import re
import sys
import os
import shutil
import json  # NEW

# ===== EXE SAFE PATH =====
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# NEW JSON CONFIG
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
DEFAULT_CONFIG_FILE = os.path.join(BASE_DIR, "admin_config_default.json")

ADMIN_MODE = "--admin" in sys.argv

FONT = ("Segoe UI", 14)
TAB_FONT = ("Segoe UI", 14, "bold")

# ===== FIELD DEFINITIONS =====
FIELDS = {
    "ACCOUNTS": [
        ("ACCOUNT_CAPITAL", "ACCOUNT_CAPITAL", False, "for paper trading only"),
        ("BROKER_ACCOUNT_ID", "ACCOUNT_ID", False, ""),
        ("BROKER_API_KEY", "API_KEY", False, ""),
        # CHANGED: runtime expects CLIENT_SECRET (legacy SECRET_TOKEN still migrated in load_config)
        ("BROKER_SECRET", "CLIENT_SECRET", False, ""),
        ("BROKER_REFRESH_TOKEN", "REFRESH_TOKEN", False, ""),
        ("ENABLE_LIVE_TRADING", "ENABLE_LIVE_TRADING", False, ""),
        ("PUSHOVER_USER_KEY", "PUSHOVER_USER_KEY", False, ""),
        ("PUSHOVER_API_TOKEN", "PUSHOVER_API_TOKEN", False, ""),
        ("ADMIN_PUSHOVER_USER_KEY", "ADMIN_PUSHOVER_USER_KEY", True, ""),
        ("ADMIN_PUSHOVER_API_TOKEN", "ADMIN_PUSHOVER_API_TOKEN", True, ""),
        ("PUSHOVER_ENABLED", "PUSHOVER_ENABLED", False, ""),
        ("WINDOWS_ALERT_ENABLED", "WINDOWS_ALERT_ENABLED", False, ""),
    ],

    "ORDERS": [
        ("POSITIONS", "POSITIONS", False, "Example: 2 (contracts) or 0.05 (5% capital)"),
        ("MIN_EXPECTED_MOVE", "MIN_EM", False, ""),
        ("MAX_PREMIUM", "MAX_PREMIUM", False, ""),
        ("PROFIT_MULTIPLIER", "PROFIT_MULTIPLIER", False, ""),
        ("SPREAD_WIDTH", "SPREAD_WIDTH", False, ""),
        ("SLIPPAGE", "SLIPPAGE", False, ""),
        ("BID_ASK_SPREAD", "BID_ASK_SPREAD", False, ""),
        ("STRIKE_STEP", "STRIKE_STEP", True, ""),
        ("STRIKE_RANGE", "STRIKE_RANGE", True, ""),

        # FIXED — these are NOT admin-only
        ("MAX_CALLS_ACTIVE", "MAX_CALLS_ACTIVE", False, ""),
        ("MAX_PUTS_ACTIVE", "MAX_PUTS_ACTIVE", False, ""),
    ],

    "TIMING": [
        ("MARKET_OPEN_TIME", "MARKET_OPEN_TIME", False, ""),
        ("TRADE_START_TIME", "TRADE_START_TIME", False, ""),
        ("STOP_NEW_ENTRIES", "STOP_NEW_ENTRIES", False, ""),
        ("FORCE_EXIT_TIME", "FORCE_EXIT_TIME", False, ""),
        ("FORCE_EXIT_ENABLED", "FORCE_EXIT_ENABLED", False, ""),
        ("ORDER_TIMEOUT", "ORDER_TIMEOUT", True, "in seconds"),
        ("LOOP", "LOOP", False, "in seconds"),
    ],

    "EMA": [
        # REMOVED — EMA seconds are now hard-coded in ema_constants.py
        # ("EMA3_SECONDS", "EMA3_SECONDS", False, ""),
        # ("EMA5_SECONDS", "EMA5_SECONDS", False, ""),
        # ("EMA20_SECONDS", "EMA20_SECONDS", False, ""),

        ("NOISE_3_5", "NOISE_3_5", False, ""),
        ("NOISE_5_20", "NOISE_5_20", False, ""),
        ("EMA20_ADJUSTMENT", "EMA20_ADJUSTMENT", True, ""),
        ("EMA_MAX_STALENESS_DAYS", "EMA_MAX_STALENESS_DAYS", True, ""),
        ("EMA_FILE", "EMA_FILE", True, ""),
        # NEW: configurable historical depth for EMA rebuild/bootstrap
        ("EMA_REBUILD_DEPTH", "EMA_REBUILD_DEPTH", True, "number of 1 minute bars in rebuild"),
    ],

    # ENTIRE TAB IS NOW ADMIN-ONLY
    "RETRIES": [
        ("ORDER_RETRY_ATTEMPTS", "ORDER_RETRY_ATTEMPTS", True, ""),
        ("TOKEN_REFRESH_DELAY", "TOKEN_REFRESH_DELAY", True, ""),
        ("DATA_RETRY_ATTEMPTS", "DATA_RETRY_ATTEMPTS", True, ""),
        ("DATA_RETRY_DELAY", "DATA_RETRY_DELAY", True, ""),
        ("MAX_API_FAILURES", "MAX_API_FAILURES", True, ""),
    ]
}

# ===== HELPERS =====
def _flatten_defaults(nested_dict):
    flat = {}
    for section, items in nested_dict.items():
        if isinstance(items, dict):
            for k, v in items.items():
                flat[k] = v
        else:
            flat[section] = items
    return flat


def _parse_value_from_string(s):
    text = s.strip()

    # NEW: strip one outer quote layer if pasted value includes wrappers
    if len(text) >= 2 and ((text[0] == text[-1] == '"') or (text[0] == text[-1] == "'")):
        text = text[1:-1].strip()

    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    if re.match(r"^-?\d+$", text):
        try:
            return int(text)
        except:
            pass
    if re.match(r"^-?\d+\.\d+$", text):
        try:
            return float(text)
        except:
            pass
    return text


def _write_config_py(merged):
    """Generate legacy-style config.py with top-level assignments expected by main.py."""
    config_py_path = os.path.join(BASE_DIR, "config.py")
    with open(config_py_path, "w", encoding="utf-8", newline="\n") as f_py:
        f_py.write("# AUTO-GENERATED - DO NOT EDIT\n")
        for k, v in merged.items():
            f_py.write(f"{k} = {repr(v)}\n")


# ===== LOAD CONFIG =====
def load_config():

    if not os.path.exists(DEFAULT_CONFIG_FILE):
        messagebox.showerror("Error", "admin_config_default.json not found")
        sys.exit(1)

    with open(DEFAULT_CONFIG_FILE, "r", encoding="utf-8") as f:
        nested_defaults = json.load(f)

    flat_defaults = _flatten_defaults(nested_defaults)

    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            try:
                user_overrides = json.load(f)
            except json.JSONDecodeError:
                user_overrides = {}
    else:
        user_overrides = {}

    current = flat_defaults.copy()
    current.update(user_overrides)

    updated = False

    # BACK-COMPAT: migrate legacy SECRET_TOKEN -> CLIENT_SECRET
    if "CLIENT_SECRET" not in current and "SECRET_TOKEN" in current:
        current["CLIENT_SECRET"] = current.get("SECRET_TOKEN", "")
        updated = True

    for key, default_val in flat_defaults.items():

        if key not in current:
            current[key] = default_val
            updated = True
            continue

        val = current[key]

        try:
            if key == "POSITIONS":
                num = float(val)
                if num <= 0:
                    raise Exception()
                if num >= 1 and not float(num).is_integer():
                    raise Exception()

            elif key.endswith("_TIME"):
                if not re.match(r"^\d{2}:\d{2}:\d{2}$", str(val)):
                    raise Exception()

            elif isinstance(val, bool):
                pass

            elif isinstance(val, (int, float)):
                pass

        except:
            current[key] = default_val
            updated = True

    overrides = {}
    for k, v in current.items():
        if k in flat_defaults and v != flat_defaults[k]:
            overrides[k] = v

    with open(CONFIG_FILE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(overrides, f, indent=4)

    return current


# ===== SAVE =====
def save_config(values):

    if not os.path.exists(DEFAULT_CONFIG_FILE):
        messagebox.showerror("Error", "admin_config_default.json not found")
        return

    with open(DEFAULT_CONFIG_FILE, "r", encoding="utf-8") as f:
        nested_defaults = json.load(f)

    flat_defaults = _flatten_defaults(nested_defaults)

    typed_values = {}
    for k, v in values.items():
        typed_values[k] = _parse_value_from_string(v)

    # BACK-COMPAT: if legacy key exists in defaults but new key is set, keep both in sync
    if "CLIENT_SECRET" in typed_values and "SECRET_TOKEN" in flat_defaults:
        typed_values["SECRET_TOKEN"] = typed_values["CLIENT_SECRET"]

    overrides = {}
    for k, v in typed_values.items():
        if k in flat_defaults and v != flat_defaults[k]:
            overrides[k] = v

    with open(CONFIG_FILE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(overrides, f, indent=4)

    # ===== CONFIG.PY GENERATION (CLEAN MERGE) =====
    try:
        with open(DEFAULT_CONFIG_FILE, "r", encoding="utf-8") as f:
            nested_defaults = json.load(f)
        flat_defaults = _flatten_defaults(nested_defaults)

        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                try:
                    overrides = json.load(f)
                except json.JSONDecodeError:
                    overrides = {}
        else:
            overrides = {}

        merged = flat_defaults.copy()
        merged.update(overrides)

        # BACK-COMPAT: ensure both keys align if either exists
        if "CLIENT_SECRET" in merged and "SECRET_TOKEN" in merged:
            merged["SECRET_TOKEN"] = merged["CLIENT_SECRET"]
        elif "CLIENT_SECRET" in merged and "SECRET_TOKEN" not in merged:
            merged["SECRET_TOKEN"] = merged["CLIENT_SECRET"]
        elif "SECRET_TOKEN" in merged and "CLIENT_SECRET" not in merged:
            merged["CLIENT_SECRET"] = merged["SECRET_TOKEN"]

        _write_config_py(merged)
    except Exception as e:
        # No deletion of behavior; just report if something goes wrong
        messagebox.showerror("Error", f"Failed to generate config.py: {e}")


class ConfigEditor:

    def __init__(self, root):

        self.root = root
        self.root.geometry("900x620")   # increased height for BROKER_REFRESH_TOKEN
        self.root.resizable(False, False)

        style = ttk.Style()
        style.theme_use("default")
        style.configure("TNotebook.Tab", font=TAB_FONT,
            background="black", foreground="white")
        style.map("TNotebook.Tab",
            foreground=[("selected", "black"), ("!selected", "white")])

        self.values = load_config()
        self.entries = {}

        self.nb = ttk.Notebook(root)
        self.nb.pack(expand=True, fill="both")

        self.build_tabs()

    # ===== BUILD ALL TABS =====
    def build_tabs(self):

        for tab in self.nb.tabs():
            self.nb.forget(tab)

        self.entries = {}

        for tab, fields in FIELDS.items():

            frame = ttk.Frame(self.nb)

            # Only add tab if at least one field is visible
            visible = any(not admin or ADMIN_MODE for (_, _, admin, _) in fields)
            if not visible:
                continue

            self.nb.add(frame, text=tab)

            row = 0

            for display, key, admin, desc in fields:

                if admin and not ADMIN_MODE:
                    continue

                tk.Label(frame, text=display, font=FONT)\
                    .grid(row=row, column=0, padx=10, pady=5, sticky="w")

                entry = tk.Entry(frame, font=FONT)
                entry.insert(0, str(self.values.get(key, "")))
                entry.grid(row=row, column=1, padx=10)

                DESC_FONT = ("Segoe UI", 14, "bold")  # add near FONT/TAB_FONT constants

                tk.Label(frame, text=desc, font=DESC_FONT, fg="gray")\
                .grid(row=row, column=2, padx=10, sticky="w")

                self.entries[key] = entry
                row += 1

            btn_frame = tk.Frame(frame)
            btn_frame.place(relx=0.5, rely=1.0, anchor="s", y=-24)

            tk.Button(btn_frame, text="SAVE", font=FONT,
                      command=self.save).pack(side="left", padx=5)

            tk.Button(btn_frame, text="CANCEL", font=FONT,
                      command=self.root.destroy).pack(side="left", padx=5)

            tk.Button(btn_frame, text="RESTORE DEFAULTS", font=FONT,
                      command=self.restore_defaults).pack(side="left", padx=5)

    # ===== SAVE BUTTON =====
    def save(self):
        vals = {k: e.get() for k, e in self.entries.items()}
        save_config(vals)
        messagebox.showinfo("Saved", "Config updated.")

    # ===== RESTORE DEFAULTS =====
    def restore_defaults(self):

        if not os.path.exists(DEFAULT_CONFIG_FILE):
            messagebox.showerror("Error", "admin_config_default.json not found")
            return

        with open(DEFAULT_CONFIG_FILE, "r", encoding="utf-8") as f:
            nested_defaults = json.load(f)

        flat_defaults = _flatten_defaults(nested_defaults)

        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                try:
                    current_overrides = json.load(f)
                except json.JSONDecodeError:
                    current_overrides = {}
        else:
            current_overrides = {}

        # ⭐ UPDATED — REFRESH_TOKEN NOW PROTECTED
        protected = {
            "ACCOUNT_ID", "API_KEY", "CLIENT_SECRET", "SECRET_TOKEN", "REFRESH_TOKEN",
            "PUSHOVER_USER_KEY", "PUSHOVER_API_TOKEN",
            "ADMIN_PUSHOVER_USER_KEY", "ADMIN_PUSHOVER_API_TOKEN"
        }

        new_config = {}
        for k in protected:
            if k in current_overrides:
                new_config[k] = current_overrides[k]

        with open(CONFIG_FILE, "w", encoding="utf-8", newline="\n") as f:
            json.dump(new_config, f, indent=4)

        self.values = flat_defaults.copy()
        self.values.update(new_config)

        self.build_tabs()

        # ===== CONFIG.PY GENERATION AFTER RESTORE =====
        try:
            with open(DEFAULT_CONFIG_FILE, "r", encoding="utf-8") as f:
                nested_defaults = json.load(f)
            flat_defaults = _flatten_defaults(nested_defaults)

            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    try:
                        overrides = json.load(f)
                    except json.JSONDecodeError:
                        overrides = {}
            else:
                overrides = {}

            merged = flat_defaults.copy()
            merged.update(overrides)

            # BACK-COMPAT mirror for generated config.py
            if "CLIENT_SECRET" in merged and "SECRET_TOKEN" in merged:
                merged["SECRET_TOKEN"] = merged["CLIENT_SECRET"]
            elif "CLIENT_SECRET" in merged and "SECRET_TOKEN" not in merged:
                merged["SECRET_TOKEN"] = merged["CLIENT_SECRET"]
            elif "SECRET_TOKEN" in merged and "CLIENT_SECRET" not in merged:
                merged["CLIENT_SECRET"] = merged["SECRET_TOKEN"]

            _write_config_py(merged)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate config.py: {e}")

        messagebox.showinfo("Restored",
            "Defaults restored (credentials preserved where available).")

# ===== MAIN =====
if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()          # hide window during setup
    ConfigEditor(root)
    root.deiconify()         # show only when fully built
    root.mainloop()

# ===== v2.0.2 additive notes =====
# This block is intentionally additive-only to comply with the requirement:
# - no original code/comment/blank lines removed
# - restore_defaults remains internal to config_editor.py
# - version bump recorded above
#
# Functional summary of 2.0.2:
# 1) Restore Defaults remains fully internal in this executable source file.
# 2) Protected credential keys are preserved during restore.
# 3) Defaults continue to come from admin_config_default.json.
# 4) config.py is regenerated after save/restore from merged defaults + overrides.
# 5) config.py is written as top-level key assignments expected by main.py.
# 6) UTF-8 encoding is explicitly used for config/default json + generated config.py.
#
# Protected keys preserved by restore_defaults():
# - ACCOUNT_ID
# - API_KEY
# - SECRET_TOKEN
# - REFRESH_TOKEN
# - PUSHOVER_USER_KEY
# - PUSHOVER_API_TOKEN
# - ADMIN_PUSHOVER_USER_KEY
# - ADMIN_PUSHOVER_API_TOKEN
#
# Packaging reminder (single EXE):
# pyinstaller --onefile --windowed --name config_editor ^
#   --add-data "admin_config_default.json;." ^
#   config_editor.py
#
# End of additive notes.