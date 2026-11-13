"""Auth: passwords, sessions, Google OAuth helpers."""
from pathlib import Path

import pytest

from remo import auth as A
from remo.memory import Memory


def test_password_roundtrip_and_wrong_password() -> None:
    stored = A.hash_password("correct-horse-9")
    assert A.check_password("correct-horse-9", stored) is True
    assert A.check_password("wrong-password", stored) is False
    assert A.check_password("correct-horse-9", "garbage") is False
    assert A.hash_password("same") != A.hash_password("same")  # unique salts


def test_validators() -> None:
    assert A.valid_email("a@b.co") is True
    assert A.valid_email("not-an-email") is False
    assert A.valid_password("12345678") is True
    assert A.valid_password("short") is False


def test_session_lifecycle(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "remo.db")
    user = mem.create_user("a@b.co", name="A", password_hash="h")
    assert mem.find_user_by_email("A@B.CO") is not None  # case-insensitive
    token = A.new_session_token()
    mem.create_session(user.id, A.hash_token(token), 60)
    assert mem.get_session_user(A.hash_token(token)) is not None
    assert mem.get_session_user(A.hash_token(token), now=1e12) is None  # expired
    assert mem.get_session_user("nope") is None
    mem.delete_session(A.hash_token(token))
    assert mem.get_session_user(A.hash_token(token)) is None
    mem.close()


def test_google_auth_url_carries_state_and_callback() -> None:
    url = A.google_auth_url("cid", "http://x/cb", "st8")
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=cid" in url and "state=st8" in url and "code" in url


def test_google_exchange_and_userinfo(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return self.payload

    seen: dict = {}

    def fake_post(url: str, data: dict | None = None, timeout: float = 0):
        seen["token_url"] = url
        seen["data"] = data
        return FakeResponse({"access_token": "tok"})

    def fake_get(url: str, headers: dict | None = None, timeout: float = 0):
        seen["auth"] = (headers or {}).get("Authorization")
        return FakeResponse({"email": "a@b.co", "email_verified": True})

    monkeypatch.setattr("remo.auth.requests.post", fake_post)
    monkeypatch.setattr("remo.auth.requests.get", fake_get)
    assert A.google_exchange_code("cid", "sec", "code", "http://x/cb") == "tok"
    assert seen["data"] is not None and seen["data"]["code"] == "code"
    assert A.google_userinfo("tok")["email"] == "a@b.co"
    assert seen["auth"] == "Bearer tok"
