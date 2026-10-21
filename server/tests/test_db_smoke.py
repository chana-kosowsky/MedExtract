import os
import uuid

from sqlalchemy import text

from app import db


def test_save_and_reload(test_schema):
    """שומרת רשומת בדיקה בטבלה זמנית וטוענת אותה מחיבור חדש."""
    table = f"smoke_{uuid.uuid4().hex[:8]}"
    value = "בדיקה-" + uuid.uuid4().hex[:6]
    engine = db.get_engine()
    try:
        with engine.begin() as conn:
            conn.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, note VARCHAR(50))"))
            conn.execute(text(f"INSERT INTO {table} (id, note) VALUES (1, :v)"), {"v": value})

        fresh = db.make_engine(os.environ["DATABASE_URL"], test_schema)
        with fresh.connect() as conn:
            loaded = conn.execute(text(f"SELECT note FROM {table} WHERE id = 1")).scalar_one()
        fresh.dispose()
        assert loaded == value
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
