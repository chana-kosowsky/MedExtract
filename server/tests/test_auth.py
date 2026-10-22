import time

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app


@pytest.fixture
def client(monkeypatch):
    """שרת עם משתמש מוגדר, בלי השהיה אחרי סיסמה שגויה."""
    monkeypatch.setenv("LOGIN_USER", "demo")
    monkeypatch.setenv("LOGIN_PASSWORD", "secret1")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.delenv("LOGIN_SHOW_DEMO", raising=False)
    monkeypatch.setattr(auth, "FAIL_DELAY", 0)
    return TestClient(app)


def test_data_needs_login(client):
    """בלי כניסה הנתונים חסומים; /health ומצב הכניסה פתוחים."""
    assert client.get("/api/commitments").status_code == 401
    assert client.get("/api/senders").status_code == 401
    assert client.post("/api/uploads").status_code == 401
    assert client.get("/health").status_code == 200
    assert client.get("/api/session").json() == {"required": True, "user": None, "demo": None}


def test_login_and_logout(client):
    """כניסה נכונה פותחת את הנתונים, יציאה סוגרת אותם."""
    assert client.post("/api/login", json={"username": "demo", "password": "secret1"}).status_code == 204
    assert client.get("/api/session").json()["user"] == "demo"
    assert client.get("/api/senders").status_code == 200
    assert client.post("/api/logout").status_code == 204
    assert client.get("/api/senders").status_code == 401


def test_wrong_password(client):
    """סיסמה או משתמש שגויים: 401 עם הודעה בעברית, ובלי עוגייה."""
    for user, pw in [("demo", "nope"), ("other", "secret1"), ("demo", "")]:
        r = client.post("/api/login", json={"username": user, "password": pw})
        assert r.status_code == 401 and r.json()["detail"] == "שם המשתמש או הסיסמה שגויים."
    assert client.get("/api/senders").status_code == 401


def test_forged_or_expired_token(client, monkeypatch):
    """עוגייה מזויפת, שפג תוקפה, או של משתמש שכבר לא מוגדר, לא נכנסת."""
    good = auth.make_token("demo")
    assert auth.token_user(good) == "demo"
    assert auth.token_user(good.replace("demo", "admin", 1)) is None
    assert auth.token_user(good[:-1] + ("0" if good[-1] != "0" else "1")) is None
    assert auth.token_user(auth.make_token("demo", now=time.time() - 8 * 86400)) is None
    assert auth.token_user("garbage") is None and auth.token_user(None) is None
    monkeypatch.setenv("LOGIN_USER", "someone-else")
    assert auth.token_user(good) is None


def test_demo_hint_only_when_enabled(client, monkeypatch):
    """פרטי הדמו מוצגים במסך הכניסה רק כשהוגדר LOGIN_SHOW_DEMO."""
    monkeypatch.setenv("LOGIN_SHOW_DEMO", "true")
    assert client.get("/api/session").json()["demo"] == {"username": "demo", "password": "secret1"}


def test_login_off_when_no_user(client, monkeypatch):
    """בלי LOGIN_USER (פיתוח) הכניסה כבויה והנתונים פתוחים."""
    monkeypatch.delenv("LOGIN_USER")
    assert client.get("/api/session").json() == {"required": False, "user": None, "demo": None}
    assert client.get("/api/senders").status_code == 200
