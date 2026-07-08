__version__ = "2.1.0"
# Copyright 2026 Gregory Howard. All rights reserved.

import os
import json
from tkinter import messagebox


# NEW JSON-BASED RESTORE DEFAULTS
ADMIN_DEFAULTS_FILE = "admin_config_default.json"   # nested, source of truth
USER_CONFIG_FILE = "config.json"                    # flat, user overrides only


def restore_defaults(self):
    """
    Restore defaults by rewriting config.json so that:
        - All user overrides are removed
        - Protected keys (API keys, tokens, account IDs) are preserved
        - admin_config_default.json is NEVER modified
    """

    # 1. Ensure admin defaults exist
    if not os.path.exists(ADMIN_DEFAULTS_FILE):
        messagebox.showerror("Error", "admin_config_default.json not found")
        return

    # 2. Load admin defaults (nested)
    try:
        with open(ADMIN_DEFAULTS_FILE, "r") as f:
            admin_defaults = json.load(f)
    except Exception as e:
        messagebox.showerror("Error", f"Failed to load admin defaults: {e}")
        return

    # 3. Load current user config (flat)
    if os.path.exists(USER_CONFIG_FILE):
        try:
            with open(USER_CONFIG_FILE, "r") as f:
                user_config = json.load(f)
        except Exception:
            user_config = {}
    else:
        user_config = {}

    # 4. Protected keys (preserve these)
    protected = {
        "ACCOUNT_ID",
        "API_KEY",
        "SECRET_TOKEN",
        "REFRESH_TOKEN",
        "PUSHOVER_USER_KEY",
        "PUSHOVER_API_TOKEN",
        "ADMIN_PUSHOVER_USER_KEY",
        "ADMIN_PUSHOVER_API_TOKEN",
    }

    # 5. Build new config.json containing ONLY protected keys
    new_config = {}

    for key in protected:
        if key in user_config:
            new_config[key] = user_config[key]

    # 6. Write the new config.json
    try:
        with open(USER_CONFIG_FILE, "w") as f:
            json.dump(new_config, f, indent=4)
    except Exception as e:
        messagebox.showerror("Error", f"Failed to write config.json: {e}")
        return

    # 7. Notify user
    messagebox.showinfo(
        "Restored",
        "Defaults restored.\nCredentials preserved."
    )

    # 8. Close the GUI window
    self.root.destroy()
