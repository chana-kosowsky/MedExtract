"""כניסה למערכת: משתמש אחד מ-.env, ועוגייה חתומה. בלי הגדרת משתמש הכניסה כבויה (פיתוח ובדיקות)."""
import hashlib
import hmac
import logging
import os
import secrets
import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

log = logging.getLogger("medextract")

COOKIE = "medextract_session"
SESSION_DAYS = 7
FAIL_DELAY = 0.5  # השהיה אחרי סיסמה שגויה, כדי להאט ניחושים

# בלי SESSION_SECRET: מפתח אקראי לכל הפעלה של השרת (הכניסות מתאפסות בהפעלה מחדש)
_fallback_secret = secrets.token_hex(32)


def _user() -> str | None:
    """שם המשתמש שמוגדר בשרת, או None כשהכניסה כבויה."""
    return (os.getenv("LOGIN_USER") or "").strip() or None


def _secret() -> bytes:
    """מפתח החתימה של העוגייה."""
    return (os.getenv("SESSION_SECRET") or _fallback_secret).encode()


def _sign(text: str) -> str:
    """חתימת HMAC לטקסט."""
    return hmac.new(_secret(), text.encode(), hashlib.sha256).hexdigest()


def make_token(user: str, now: float | None = None) -> str:
    """עוגייה: משתמש, תוקף וחתימה."""
    expires = int((now or time.time()) + SESSION_DAYS * 86400)
    body = f"{user}|{expires}"
    return f"{body}|{_sign(body)}"


def token_user(token: str | None, now: float | None = None) -> str | None:
    """המשתמש שבעוגייה, אם החתימה תקינה, התוקף לא עבר והמשתמש עדיין מוגדר בשרת."""
    try:
        user, expires, sig = (token or "").rsplit("|", 2)
        valid = hmac.compare_digest(sig, _sign(f"{user}|{expires}")) and int(expires) > (now or time.time())
    except ValueError:
        return None
    return user if valid and user == _user() else None


def require_login(request: Request) -> None:
    """כל נקודות הקצה של הנתונים: בלי כניסה תקינה, 401."""
    if _user() and not token_user(request.cookies.get(COOKIE)):
        raise HTTPException(401, "צריך להתחבר מחדש.")


router = APIRouter(prefix="/api")


class LoginIn(BaseModel):
    username: str
    password: str


def _show_demo() -> bool:
    """האם להציג במסך הכניסה את פרטי משתמש הדמו."""
    return os.getenv("LOGIN_SHOW_DEMO", "").strip().lower() in ("1", "true", "yes")


@router.get("/session")
def session(request: Request):
    """מצב הכניסה: האם צריך להתחבר, מי מחובר, ופרטי הדמו להצגה (אם הוגדר)."""
    required = _user() is not None
    demo = {"username": _user(), "password": os.getenv("LOGIN_PASSWORD", "")} if required and _show_demo() else None
    return {"required": required, "user": token_user(request.cookies.get(COOKIE)) if required else None, "demo": demo}


@router.post("/login", status_code=204)
def login(body: LoginIn, request: Request, response: Response):
    """בדיקת שם משתמש וסיסמה, ועוגייה חתומה לשבוע."""
    user, password = _user(), os.getenv("LOGIN_PASSWORD", "")
    ok_user = user is not None and hmac.compare_digest(body.username.strip(), user)
    ok_pass = bool(password) and hmac.compare_digest(body.password, password)
    if not (ok_user and ok_pass):
        time.sleep(FAIL_DELAY)
        log.info("login failed")
        raise HTTPException(401, "שם המשתמש או הסיסמה שגויים.")
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, make_token(user), max_age=SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=secure)
    log.info("login ok")


@router.post("/logout", status_code=204)
def logout(response: Response):
    """יציאה: מחיקת העוגייה."""
    response.delete_cookie(COOKIE)
