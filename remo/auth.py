"""Accounts: email+password and Google OAuth over server-side sessions.

Passwords are PBKDF2-HMAC-SHA256 (stdlib only, no new dependency). Sessions are
opaque tokens: only a SHA-256 hash is stored, the token itself lives in an
HttpOnly cookie. Google sign-in uses the plain OAuth2 code flow; accounts link
by verified email.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from urllib.parse import urlencode

import requests

SESSION_COOKIE = "remo_session"
SESSION_TTL_SECONDS = 30 * 24 * 3600
OAUTH_STATE_COOKIE = "remo_oauth_state"

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

_PBKDF2_ROUNDS = 200_000
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email.strip()))


def valid_password(password: str) -> bool:
    return len(password) >= 8


def hash_password(password: str) -> str:
    """salt$rounds$hex — verifiable with nothing but the stored string."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS).hex()
    return f"{salt.hex()}${_PBKDF2_ROUNDS}${digest}"


def check_password(password: str, stored: str) -> bool:
    try:
        salt_hex, rounds, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
        ).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, digest)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_oauth_state() -> str:
    return secrets.token_urlsafe(24)


def google_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def google_exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str) -> str:
    """Trade an auth code for an access token (raises on any failure)."""
    resp = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return str(resp.json()["access_token"])


def google_userinfo(access_token: str) -> dict:
    """Verified profile for an access token (raises on any failure)."""
    resp = requests.get(
        GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=15
    )
    resp.raise_for_status()
    return dict(resp.json())


def session_cookie_kwargs(secure: bool) -> dict:
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": secure,
        "max_age": SESSION_TTL_SECONDS,
        "path": "/",
    }


def now() -> float:
    return time.time()
