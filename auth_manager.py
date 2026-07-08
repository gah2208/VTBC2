__version__ = "1.0.2"
# copyright (c) Gregory Howard 2026  all rights reserved

import os
import json
import uuid
import requests
import hashlib
import socket
import sys
import subprocess
from tkinter import messagebox

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.py")
UPDATE_SCRIPT = os.path.join(BASE_DIR, "Update.bat")

AUTH_URL = "https://raw.githubusercontent.com/gah2208/vtbc/main/auth.json"

# ✅ APPLICATION VERSION
APP_VERSION = 1.1


def _parse_version(value):
    try:
        if isinstance(value, (int, float)):
            return tuple(int(part) for part in str(value).split("."))
        return tuple(int(part) for part in str(value).strip().split("."))
    except Exception:
        return ()


# ===== LOAD CONFIG =====
def load_config():
    values = {}
    with open(CONFIG_FILE) as f:
        for line in f:
            if "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip('"')
    return values


# ===== MACHINE ID =====
def get_machine_id():
    raw = str(uuid.getnode())
    return hashlib.md5(raw.encode()).hexdigest()[:8]


# ===== USER NAME =====
def get_user_name():
    try:
        return os.getlogin()
    except:
        return socket.gethostname()


# ===== ADMIN ALERT =====
def send_admin_alert(msg):
    cfg = load_config()

    token = cfg.get("ADMIN_PUSHOVER_API_TOKEN", "")
    user = cfg.get("ADMIN_PUSHOVER_USER_KEY", "")

    if not token or not user:
        return

    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": token,
                "user": user,
                "message": msg
            },
            timeout=5
        )
    except:
        pass


# ===== FETCH AUTH =====
def fetch_auth():
    try:
        r = requests.get(AUTH_URL, timeout=5)
        if r.status_code != 200:
            return None
        return r.json()
    except:
        return None


# ===== VERSION CHECK =====
def check_version_and_prompt(data):

    min_version = data.get("min_version")

    if min_version is None:
        return True

    current_version = _parse_version(APP_VERSION)
    required_version = _parse_version(min_version)

    if required_version and current_version >= required_version:
        return True

    result = messagebox.askyesno(
        "Update Available",
        f"A newer version is available.\n\n"
        f"Current version: {APP_VERSION}\n"
        f"Required version: {min_version}\n\n"
        f"Would you like to update now?"
    )

    if result:
        run_update()
        sys.exit(0)

    return True


# ===== AUTH CHECK =====
def check_authorization(data):

    machine_id = get_machine_id()
    users = data.get("users", {})

    if machine_id not in users:
        return False

    return users[machine_id].get("enabled", False)


# ===== RUN UPDATE =====
def run_update():

    if os.path.exists(UPDATE_SCRIPT):
        try:
            if os.name == "nt":
                subprocess.Popen(["cmd", "/c", UPDATE_SCRIPT])
            else:
                subprocess.Popen([UPDATE_SCRIPT])
        except:
            pass


# ===== MAIN ENFORCER =====
def enforce_auth():

    data = fetch_auth()

    # ❌ FAIL-CLOSED: GitHub not available
    if not data:
        messagebox.showerror(
            "Authorization Error",
            "GitHub authorization not available.\n\n"
            "Check your internet connection and try again."
        )
        sys.exit(1)

    # ✅ VERSION CHECK (SOFT PROMPT)
    check_version_and_prompt(data)

    # ✅ AUTH CHECK
    if check_authorization(data):
        return True

    # ❌ UNAUTHORIZED → SEND ALERT
    msg = (
        "UNAUTHORIZED ACCESS ATTEMPT\n\n"
        f"User: {get_user_name()}\n"
        f"Machine ID: {get_machine_id()}"
    )

    send_admin_alert(msg)

    return False