__version__ = "2.1.5"
# Copyright 2026 Gregory Howard

import requests
import time
import json
import os
import uuid

# ============================================================
# CONFIG IMPORT
# ============================================================
# CHANGE: Use config_loader to get merged config instead of importing from config
from config_loader import load_merged_config

# Load merged config and extract constants at module startup
_cfg = load_merged_config()

def _clean(v):
    if v is None:
        return ""
    s = str(v).strip()
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        s = s[1:-1].strip()
    return s

ORDER_RETRY_ATTEMPTS = _cfg.get("ORDER_RETRY_ATTEMPTS", 3)
TOKEN_REFRESH_DELAY = _cfg.get("TOKEN_REFRESH_DELAY", 1)
DATA_RETRY_ATTEMPTS = _cfg.get("DATA_RETRY_ATTEMPTS", 3)
DATA_RETRY_DELAY = _cfg.get("DATA_RETRY_DELAY", 0.5)
MAX_API_FAILURES = _cfg.get("MAX_API_FAILURES", 5)
ORDER_TIMEOUT = _cfg.get("ORDER_TIMEOUT", 180)

# NEW: client secret for OAuth confidential-client refresh flow
# Supports both new key (CLIENT_SECRET) and legacy key (SECRET_TOKEN)
CLIENT_SECRET = _clean(_cfg.get("CLIENT_SECRET", "") or _cfg.get("SECRET_TOKEN", ""))

# NEW: Export these constants so they can be imported by other modules
__all__ = [
    'TSClient',
    'ORDER_RETRY_ATTEMPTS',
    'TOKEN_REFRESH_DELAY',
    'DATA_RETRY_ATTEMPTS',
    'DATA_RETRY_DELAY',
    'MAX_API_FAILURES',
    'ORDER_TIMEOUT'
]

# OLD CONFIG IMPORT (commented out - using config_loader instead)
# from config import (
#     ORDER_RETRY_ATTEMPTS,
#     TOKEN_REFRESH_DELAY,
#     DATA_RETRY_ATTEMPTS,
#     DATA_RETRY_DELAY,
#     MAX_API_FAILURES
# )

# ============================================================
# OPTIONAL DEBUG LOGGING
# ============================================================
DEBUG_LOG = True   # Set to False to disable logging

# New: default request timeout (seconds)
REQUEST_TIMEOUT = 10

# NEW: split timeouts (connect, read) to prevent long SSL read hangs
CONNECT_TIMEOUT = _cfg.get("CONNECT_TIMEOUT", 3.05)
READ_TIMEOUT = _cfg.get("READ_TIMEOUT", REQUEST_TIMEOUT)
DEFAULT_TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)


def _log(msg):
    if DEBUG_LOG:
        print(f"[TSClient] {msg}")


class TSClient:

    # ========================================================
    # SIM vs LIVE ENDPOINTS
    # ========================================================
    BASE_URL_SIM  = "https://sim-api.tradestation.com/v3"
    BASE_URL_LIVE = "https://api.tradestation.com/v3"

    AUTH_URL = "https://signin.tradestation.com/oauth/token"

    def __init__(self, api_key, refresh_token, account_id, live=False):
        """
        live=False  → SIM trading
        live=True   → LIVE trading
        """

        self.api_key = _clean(api_key)
        self.refresh_token = _clean(refresh_token)
        self.account_id = _clean(account_id)

        self.base_url = self.BASE_URL_LIVE if live else self.BASE_URL_SIM

        self.access_token = None
        self.token_expiry = 0
        self.fail_count = 0

        # NEW: persistent HTTP session for connection reuse
        self.session = requests.Session()

        _log(f"Initialized TSClient (live={live})")
        self._refresh_access_token()


    # ========================================================
    # TOKEN REFRESH
    # ========================================================
    def _refresh_access_token(self):

        _log("Refreshing access token...")

        for attempt in range(ORDER_RETRY_ATTEMPTS):

            try:
                # NEW DEBUG: verify runtime values (masked)
                _log(f"AUTH DEBUG keys has CLIENT_SECRET: {'CLIENT_SECRET' in _cfg}")
                _log(f"AUTH DEBUG keys has SECRET_TOKEN: {'SECRET_TOKEN' in _cfg}")
                _log(f"AUTH DEBUG client_id suffix: ...{str(self.api_key)[-6:] if self.api_key else 'MISSING'}")
                _log(f"AUTH DEBUG refresh_token len: {len(str(self.refresh_token)) if self.refresh_token else 0}")
                _log(f"AUTH DEBUG client_secret len: {len(str(CLIENT_SECRET)) if CLIENT_SECRET else 0}")

                # OLD: direct requests.post
                # r = requests.post(self.AUTH_URL, data={
                #     "grant_type": "refresh_token",
                #     "refresh_token": self.refresh_token,
                #     "client_id": self.api_key
                # })

                # NEW: include client_secret in refresh request body (Version A, confirmed working)
                r = self.session.post(self.AUTH_URL, data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "client_id": self.api_key,
                    "client_secret": CLIENT_SECRET
                }, timeout=DEFAULT_TIMEOUT)

                # NEW DEBUG: response visibility
                _log(f"AUTH DEBUG HTTP {r.status_code}")
                try:
                    _log(f"AUTH DEBUG BODY {r.text}")
                except Exception:
                    pass

                # OLD (commented out)
                # data = r.json()

                # NEW SAFE JSON
                data = self._safe_json(r)

                if "access_token" not in data:
                    raise Exception(f"Bad token response: {data}")

                self.access_token = data["access_token"]
                self.token_expiry = time.time() + data["expires_in"] - 60

                _log("Access token refreshed successfully.")
                return

            except Exception as e:
                _log(f"Token refresh failed: {e}")
                time.sleep(TOKEN_REFRESH_DELAY)

        raise Exception("AUTH FAIL — Could not refresh access token")


    # ========================================================
    # HEADERS
    # ========================================================
    def _headers(self):

        if time.time() >= self.token_expiry:
            self._refresh_access_token()

        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }


    # ========================================================
    # NEW SAFE JSON WRAPPER
    # ========================================================
    def _safe_json(self, r):
        try:
            return r.json()
        except Exception:
            try:
                _log(f"Failed to parse JSON. Response text: {r.text}")
            except Exception:
                pass
            return {}


    # ========================================================
    # GENERIC REQUEST WRAPPER
    # ========================================================
    def _req(self, method, url, **kwargs):

        # Allow callers to override per-call timeout (business-level)
        # Accept either single float/int OR tuple(connect, read)
        timeout = kwargs.pop("timeout", DEFAULT_TIMEOUT)

        for attempt in range(DATA_RETRY_ATTEMPTS):

            try:
                _log(f"REQUEST → {url}")
                if "json" in kwargs:
                    try:
                        _log(f"PAYLOAD → {json.dumps(kwargs['json'], indent=2)}")
                    except Exception:
                        _log("PAYLOAD → <unserializable>")

                # OLD: direct call via method
                # r = method(url, headers=self._headers(), **kwargs)

                # NEW: route common requests.* methods through the session to
                # apply consistent timeout and connection reuse. If `method` is
                # not a requests function, call it directly.
                func = method
                try:
                    # map requests.get/post/delete/put to session counterparts
                    if method in (requests.get, requests.post, requests.delete, requests.put, requests.patch):
                        func = getattr(self.session, method.__name__)
                except Exception:
                    func = method

                r = func(url, headers=self._headers(), timeout=timeout, **kwargs)

                # OLD: only treat 200 as success
                # if r.status_code == 200:

                # NEW: accept any 2xx as success
                if 200 <= r.status_code < 300:
                    self.fail_count = 0

                    # handle empty 204 responses
                    if r.status_code == 204:
                        return {}

                    # OLD (commented out)
                    # return r.json()

                    # NEW SAFE JSON
                    return self._safe_json(r)

                _log(f"Non-200 response: {r.status_code} {r.text}")

            except requests.exceptions.Timeout:
                _log(f"Request timeout (attempt {attempt + 1}/{DATA_RETRY_ATTEMPTS}) url={url} timeout={timeout}")
            except requests.exceptions.ConnectionError as e:
                _log(f"Connection error (attempt {attempt + 1}/{DATA_RETRY_ATTEMPTS}) url={url} err={e}")
            except Exception as e:
                _log(f"Request error (attempt {attempt + 1}/{DATA_RETRY_ATTEMPTS}) url={url} err={e}")

            time.sleep(DATA_RETRY_DELAY)

        self.fail_count += 1

        if self.fail_count >= MAX_API_FAILURES:
            raise Exception("API FAILURE — Too many consecutive failures")

        # NEW SAFE FALLBACK
        return {}


    # ========================================================
    # PUBLIC API METHODS
    # ========================================================
    def get_spx_price(self):
        return self._req(
            requests.get,
            f"{self.base_url}/marketdata/quotes/SPX"
        )


    # OLD: get_quotes did not accept a per-call timeout, so callers passing
    # timeout=(connect, read) (e.g. main.py) raised:
    #   TypeError: get_quotes() got an unexpected keyword argument 'timeout'
    # (COMMENTED OUT — kept for reference, not deleted)
    # def get_quotes(self, symbols):
    #     return self._req(
    #         requests.get,
    #         f"{self.base_url}/marketdata/quotes/" + ",".join(symbols)
    #     )

    # NEW: accept an optional per-call timeout and forward it to _req, mirroring
    # place_order(). When timeout is None we DO NOT pass it, so _req falls back to
    # its DEFAULT_TIMEOUT instead of receiving None (which would disable timeout).
    def get_quotes(self, symbols, timeout=None):
        url = f"{self.base_url}/marketdata/quotes/" + ",".join(symbols)
        if timeout is not None:
            return self._req(
                requests.get,
                url,
                timeout=timeout
            )
        return self._req(
            requests.get,
            url
        )


    def place_order(self, payload, client_ref=None, timeout=None):
        """
        payload MUST contain:
            - OrderType
            - LimitPrice (if OrderType is Limit)
            - Legs: [ {Symbol, TradeAction, Quantity}, ... ]

        NEW: Supports optional client_ref (clientOrderId) for idempotency.
        If initial POST is ambiguous (timeout/no body), queries by client_ref
        before re-submitting to avoid duplicate orders.
        """

        url = f"{self.base_url}/orderexecution/orders"

        # NEW: Generate unique client reference if not provided
        if client_ref is None:
            client_ref = f"vtbc-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"

        # NEW: Attach clientOrderId to payload for idempotency tracking
        try:
            if "clientOrderId" not in payload and "ClientOrderId" not in payload:
                payload["clientOrderId"] = client_ref
        except Exception:
            # payload might not be a dict; in that case, just continue
            pass

        # NEW: Determine call timeout (use provided or ORDER_TIMEOUT from config)
        call_timeout = timeout if timeout is not None else ORDER_TIMEOUT

        # OLD: Simple _req call without timeout parameter
        # r = self._req(
        #     requests.post,
        #     url,
        #     json=payload
        # )

        # NEW: Use business-level ORDER_TIMEOUT for order submission
        r = self._req(
            requests.post,
            url,
            json=payload,
            timeout=call_timeout
        )

        # Try to extract OrderID from immediate response
        if r:
            # OLD (commented out)
            # _log(f"Order placed. OrderID={r.get('OrderID')}")
            # return r.get("OrderID")

            # NEW: Try multiple possible ID field names
            oid = r.get("OrderID") or r.get("orderId") or r.get("id")
            if oid:
                _log(f"Order placed. OrderID={oid}")
                return oid

        # NEW: Ambiguous result (timeout or no body). Avoid blind re-submit: query by client ref.
        _log(f"Order submission ambiguous — looking up by client_ref={client_ref}")

        lookup = self.get_order_by_client_ref(client_ref, timeout=call_timeout)

        # NEW: Attempt to extract order id from lookup result
        def _extract_order_id(resp):
            if not resp:
                return None
            if isinstance(resp, dict):
                for k in ("OrderID", "orderId", "id"):
                    if k in resp and resp[k]:
                        return resp[k]
                # look for lists of orders in values
                for v in resp.values():
                    if isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                        for k in ("OrderID", "orderId", "id"):
                            if k in v[0] and v[0][k]:
                                return v[0][k]
                return None
            if isinstance(resp, list) and len(resp) > 0 and isinstance(resp[0], dict):
                for k in ("OrderID", "orderId", "id"):
                    if k in resp[0] and resp[0][k]:
                        return resp[0][k]
            return None

        oid = _extract_order_id(lookup)
        if oid:
            _log(f"Found order by client_ref. OrderID={oid}")
            return oid

        # NEW: No order found by client_ref; do not re-submit blindly
        _log("No order found by client_ref; submission considered failed (no duplicate submit)")
        return None

    def get_order(self, oid):
        return self._req(
            requests.get,
            f"{self.base_url}/orderexecution/orders/{oid}"
        )

    def cancel_order(self, oid):
        return self._req(
            requests.delete,
            f"{self.base_url}/orderexecution/orders/{oid}"
        )

    # ========================================================
    # NEW: Lookup order(s) by client reference (clientOrderId)
    # ========================================================
    def get_order_by_client_ref(self, client_ref, timeout=None):
        """
        Query the orders endpoint for orders that match the provided
        clientOrderId (client_ref). Returns the API response (dict) or {}
        if none found or on error.
        """
        if timeout is None:
            return self._req(
                requests.get,
                f"{self.base_url}/orderexecution/orders?clientOrderId={client_ref}"
            )
        else:
            return self._req(
                requests.get,
                f"{self.base_url}/orderexecution/orders?clientOrderId={client_ref}",
                timeout=timeout
            )