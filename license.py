__version__ = "1.1.1"
# Copyright 2026 Gregory Howard  all rights reserved.

import requests
import hashlib
import socket
import uuid
import json
import os
import time
from datetime import datetime

AUTH_URL = "https://raw.githubusercontent.com/gah2208/VTBC/main/auth.json"

CACHE_FILE = "auth_cache.json"
CACHE_TTL_SECONDS = 3600  # 1 hour


def get_user_id():
    raw = f"{socket.gethostname()}-{uuid.getnode()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:8]


def fetch_auth():

    try:
        r = requests.get(AUTH_URL, timeout=5)
        r.raise_for_status()
        data = r.json()

        # ✅ Save cache
        with open(CACHE_FILE, "w") as f:
            json.dump({
                "timestamp": time.time(),
                "data": data
            }, f)

        return data

    except Exception:

        # ✅ Attempt cache fallback
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                cache = json.load(f)

                age = time.time() - cache.get("timestamp", 0)

                if age <= CACHE_TTL_SECONDS:
                    return cache.get("data")

        # ❌ No valid cache
        raise Exception("AUTH FETCH FAILED AND CACHE EXPIRED")


def parse_version_strict(v):
    """
    Parse a dotted numeric version string like '1.3.3' into a tuple (1, 3, 3).
    Rejects invalid formats (empty, non-numeric segments, etc.).
    """
    s = str(v).strip()
    if not s:
        raise ValueError("empty version")

    parts = s.split(".")
    if any(part == "" for part in parts):
        raise ValueError(f"invalid version format: {v}")

    nums = []
    for part in parts:
        if not part.isdigit():
            raise ValueError(f"non-numeric version segment: {part}")
        nums.append(int(part))

    return tuple(nums)


def compare_versions(current, minimum):
    """
    Returns:
      -1 if current < minimum
       0 if current == minimum
       1 if current > minimum
    """
    c = parse_version_strict(current)
    m = parse_version_strict(minimum)

    max_len = max(len(c), len(m))
    c += (0,) * (max_len - len(c))
    m += (0,) * (max_len - len(m))

    if c < m:
        return -1
    if c > m:
        return 1
    return 0


def check_license(system_version):

    user_id = get_user_id()
    auth = fetch_auth()

    users = auth.get("users", {})

    if user_id not in users:
        return False, f"UNAUTHORIZED USER: {user_id}"

    user = users[user_id]

    if not user.get("enabled", False):
        return False, f"USER DISABLED: {user_id}"

    min_version = auth.get("min_version", "0")

    try:
        if compare_versions(system_version, min_version) < 0:
            return False, f"VERSION TOO OLD: {system_version} < {min_version}"
    except ValueError as e:
        return False, f"INVALID VERSION FORMAT: {e}"

    exp = user.get("expires")
    if exp:
        try:
            if datetime.now().date() > datetime.strptime(exp, "%Y-%m-%d").date():
                return False, f"LICENSE EXPIRED: {exp}"
        except:
            pass

    return True, f"AUTHORIZED: {user_id}"