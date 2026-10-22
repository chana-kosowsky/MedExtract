import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth, db
from .routes import router

logging.basicConfig()
log = logging.getLogger("medextract")
log.setLevel(logging.INFO)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """בעליית השרת: יצירת טבלאות וניקוי רשומות דמו ישנות."""
    try:
        db.init()
        db.cleanup_demo()
    except Exception as e:
        log.warning("db init failed (%s)", type(e).__name__)
    yield


app = FastAPI(title="MedExtract", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(router)


@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    """מחזירה אם השרת והמסד תקינים. גם HEAD, כי שירותי פינג חינמיים שולחים HEAD."""
    try:
        db.ping()
        return {"status": "ok", "db": "ok"}
    except Exception as e:
        log.warning("health: db check failed (%s)", type(e).__name__)
        return JSONResponse(status_code=503, content={"status": "degraded", "db": "error"})


# ב-Windows הרישום עלול לתת לקובצי JS סוג text/plain, והדפדפן מסרב להריץ אותם כמודול
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")

_dist = Path(__file__).resolve().parents[2] / "client" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="client")
