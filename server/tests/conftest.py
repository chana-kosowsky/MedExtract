import os
import uuid

import pytest
from sqlalchemy import text
from sqlmodel import SQLModel

from app import db


@pytest.fixture(autouse=True)
def login_off(monkeypatch):
    """הבדיקות רצות בלי כניסה (גם אם ב-.env מוגדר משתמש); בדיקות הכניסה מגדירות אותו בעצמן."""
    monkeypatch.delenv("LOGIN_USER", raising=False)


@pytest.fixture(scope="session", autouse=True)
def test_schema():
    """כל הבדיקות רצות בסכמה זמנית נפרדת שנמחקת בסוף, ולא נוגעות בטבלאות האמיתיות."""
    schema = f"test_{uuid.uuid4().hex[:8]}"
    url = os.environ["DATABASE_URL"]
    base = db.make_engine(url)
    with base.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = db.make_engine(url, schema)
    SQLModel.metadata.create_all(engine)
    real, db._engine = db._engine, engine
    try:
        yield schema
    finally:
        engine.dispose()
        db._engine = real
        with base.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        base.dispose()
