__version__ = "1.0.0"
# copyright (c) 2026 Gregory Howard  all rights reserved 


import json
import os
import sys
import time
import webbrowser
import requests

BASE_PATH = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_PATH, "config.json")
DEFAULTS_PATH = os.path.join(BASE_PATH, "admin_config_default.json")

# ============================================================
# Helper: Load defaults and flatten
# ============================================================
def load_flat_defaults():
    with open(DEFAULTS_PATH, "r") as f:
        nested = json.load(f)

    flat = {}
    for section, items in nested.items():
        if isinstance(items, dict):
            for k, v in items.items():
                flat[k] = v
        else:
            flat[section] = items
    return flat


# ============================================================
# Helper: Write config.json (only overrides)
# ============================================================
def write_config(overrides):
    with open(CONFIG_PATH, "w") as f:
        json.dump(overrides, f, indent=4)


# ============================================================
# Step 1 — Capital confirmation
# ============================================================
print("============================================================")
print("              VTBC ONE-TIME ONBOARDING")
print("============================================================\n")

ans = input("Do you have at least $10,100 in your TradeStation account? (yes/no): ").strip().lower()
if ans != "yes":
    print("\nYou must have at least $10,050 to continue. Exiting.\n")
    time.sleep(2)
    sys.exit(1)


# ============================================================
# Step 2 — Credential confirmation
# ============================================================
print("\nYou MUST have the following values:")
print("  • API_KEY")
print("  • SECRET_TOKEN")
print("  • ACCOUNT_ID\n")

ans = input("Do you have these values? (yes/no): ").strip().lower()
if ans != "yes":
    print("\nPlease obtain your API_KEY, SECRET_TOKEN, and ACCOUNT_ID first. Exiting.\n")
    time.sleep(2)
    sys.exit(1)


# ============================================================
# Step 3 — Prompt for credentials
# ============================================================
api_key = input("\nEnter your API_KEY: ").strip()
secret_token = input("Enter your SECRET_TOKEN: ").strip()
account_id = input("Enter your ACCOUNT_ID: ").strip()

if not api_key or not secret_token or not account_id:
    print("\nERROR: All fields are required. Exiting.\n")
    sys.exit(1)


# ============================================================
# Step 4 — Load defaults and write initial config
# ============================================================
flat_defaults = load_flat_defaults()

config = {}
config["API_KEY"] = api_key
config["SECRET_TOKEN"] = secret_token
config["ACCOUNT_ID"] = account_id

write_config(config)

print("\nYour API credentials have been saved.")
print("Next, we will authenticate with TradeStation.\n")


# ============================================================
# Step 5 — Open OAuth login page
# ============================================================
AUTH_URL = (
    "https://signin.tradestation.com/authorize?"
    f"response_type=code&client_id={api_key}"
    "&redirect_uri=https://localhost"
    "&audience=https://api.tradestation.com"
)

print("A browser window will now open.")
print("Log in to TradeStation and approve access.")
print("You will be redirected to:")
print("    https://localhost/?code=XXXXXXXX")
print("\nCopy the value after 'code=' and paste it below.\n")

webbrowser.open(AUTH_URL)

auth_code = input("Paste the code from your browser here: ").strip()

if not auth_code:
    print("\nERROR: No code entered. Exiting.\n")
    sys.exit(1)


# ============================================================
# Step 6 — Exchange code for refresh token
# ============================================================
TOKEN_URL = "https://signin.tradestation.com/oauth/token"

payload = {
    "grant_type": "authorization_code",
    "client_id": api_key,
    "client_secret": secret_token,
    "code": auth_code,
    "redirect_uri": "https://localhost"
}

print("\nRequesting tokens from TradeStation...\n")

response = requests.post(TOKEN_URL, data=payload)

if response.status_code != 200:
    print("ERROR:", response.status_code, response.text)
    sys.exit(1)

data = response.json()
refresh_token = data.get("refresh_token")

if not refresh_token:
    print("\nERROR: No refresh token returned. Cannot continue.\n")
    sys.exit(1)


# ============================================================
# Step 7 — Write refresh token into config.json
# ============================================================
config["REFRESH_TOKEN"] = refresh_token
write_config(config)

print("============================================================")
print("SUCCESS — Your VTBC installation is now authenticated.")
print("============================================================\n")
print("Your refresh token has been securely written to config.json.")
print("VTBC is now ready to trade using your TradeStation account.\n")

time.sleep(3)
