__version__ = "1.0.1"
# Copyright (c) 2026 Gregory Howard  all rights reserved

import json
import os
import sys

# Resolve base directory correctly for both:
# - normal python execution
# - PyInstaller onefile executable
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULTS_PATH = os.path.join(BASE_DIR, "admin_config_default.json")
USER_CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


# ------------------------------------------------------------
# Flatten nested admin defaults
# ------------------------------------------------------------
def _flatten_defaults(nested):
    flat = {}
    for section, items in nested.items():
        if isinstance(items, dict):
            for k, v in items.items():
                flat[k] = v
        else:
            flat[section] = items
    return flat


# ------------------------------------------------------------
# Load merged config (defaults + overrides)
# ------------------------------------------------------------
def load_merged_config():
    # 1. Load admin defaults (nested)
    if not os.path.exists(DEFAULTS_PATH):
        raise FileNotFoundError(
            f"admin_config_default.json not found at: {DEFAULTS_PATH}"
        )

    with open(DEFAULTS_PATH, "r", encoding="utf-8") as f:
        nested_defaults = json.load(f)

    flat_defaults = _flatten_defaults(nested_defaults)

    # 2. Load user overrides (flat)
    if os.path.exists(USER_CONFIG_PATH):
        try:
            with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
                overrides = json.load(f)
        except json.JSONDecodeError:
            overrides = {}
    else:
        overrides = {}

    # 3. Merge → defaults first, then overrides
    merged = flat_defaults.copy()
    merged.update(overrides)

    return merged


# ------------------------------------------------------------
# Optional helper: load a single key with fallback
# ------------------------------------------------------------
def get_config_value(key, default=None):
    cfg = load_merged_config()
    return cfg.get(key, default)