#!/usr/bin/env python3
import argparse
import json
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

AUTH_BASE = "https://signin.tradestation.com/authorize"
TOKEN_URL = "https://signin.tradestation.com/oauth/token"
AUDIENCE = "https://api.tradestation.com"

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        self.server.oauth_query = qs

        ok = "code" in qs
        body = (
            b"<html><body><h2>Authorization received. You can close this tab.</h2></body></html>"
            if ok else
            b"<html><body><h2>Authorization failed/cancelled. You can close this tab.</h2></body></html>"
        )
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass

def build_authorize_url(client_id, redirect_uri, scopes, state):
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "audience": AUDIENCE,
        "scope": scopes,
        "state": state,
    }
    return f"{AUTH_BASE}?{urllib.parse.urlencode(params)}"

def exchange_code_for_tokens(client_id, client_secret, redirect_uri, code):
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "redirect_uri": redirect_uri,
    }
    if client_secret:
        data["client_secret"] = client_secret

    r = requests.post(
        TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30
    )

    if r.status_code >= 400:
        try:
            err = r.json()
        except Exception:
            err = {"raw": r.text}
        raise RuntimeError(f"Token exchange failed ({r.status_code}): {json.dumps(err)}")

    return r.json()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-id", required=True)
    ap.add_argument("--client-secret", default="", help="Required for confidential apps")
    ap.add_argument("--redirect-uri", required=True)
    ap.add_argument("--scopes", default="openid profile offline_access MarketData ReadAccount Trade OptionSpreads")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    u = urllib.parse.urlparse(args.redirect_uri)
    if u.scheme not in ("http", "https") or not u.hostname or not u.port:
        raise SystemExit("redirect-uri must include scheme/host/port, e.g. http://localhost:8080")

    state = secrets.token_urlsafe(24)

    httpd = HTTPServer((u.hostname, u.port), OAuthCallbackHandler)
    httpd.oauth_query = None
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    auth_url = build_authorize_url(args.client_id, args.redirect_uri, args.scopes, state)
    print("\nOpen this URL to authorize:\n")
    print(auth_url)
    print("\nAttempting to open browser...\n")
    webbrowser.open(auth_url)

    deadline = time.time() + args.timeout
    try:
        while time.time() < deadline:
            if httpd.oauth_query is not None:
                break
            time.sleep(0.2)
    finally:
        httpd.shutdown()
        t.join(timeout=2)

    qs = httpd.oauth_query
    if not qs:
        raise SystemExit("Timed out waiting for OAuth callback.")
    if "error" in qs:
        raise SystemExit(f"OAuth error: {qs.get('error',[None])[0]} {qs.get('error_description',[''])[0]}")
    if qs.get("state", [""])[0] != state:
        raise SystemExit("State mismatch.")
    code = qs.get("code", [""])[0]
    if not code:
        raise SystemExit("No code in callback.")

    tokens = exchange_code_for_tokens(args.client_id, args.client_secret, args.redirect_uri, code)

    print("\n=== TOKEN RESPONSE ===")
    print(json.dumps(tokens, indent=2))

    if "refresh_token" in tokens:
        print("\n=== REFRESH TOKEN ===")
        print(tokens["refresh_token"])
    else:
        print("\nNo refresh_token returned. Ensure offline_access scope is allowed for this app.")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(tokens, f, indent=2)
        print(f"\nSaved token JSON to: {args.out}")

if __name__ == "__main__":
    main()