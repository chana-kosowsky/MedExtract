import logging
import re
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartParser

from . import db, export, pipeline
from .extractor import ExtractionError, build_extractor
from .validation import SENDERS, short_sender_name

log = logging.getLogger("medextract")

# קבצים עד התקרה נשארים בזיכרון ולא נכתבים לקובץ זמני (ברירת המחדל: דיסק מעל 1MB)
MultiPartParser.max_file_size = pipeline.MAX_TOTAL_BYTES

router = APIRouter(prefix="/api")

EXPORT_MAX = 5000
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _job_or_404(job_id: str) -> pipeline.Job:
    """מחזירה עבודה או שגיאה 404 בעברית."""
    job = pipeline.get_job(job_id)
    if not job:
        raise HTTPException(404, "העבודה לא נמצאה.")
    return job


def _parse_resume(resume_of, skip) -> tuple[str | None, set[tuple[int, int]]]:
    """מפענחת שדות המשך העלאה; ערך לא תקין זורק שגיאה."""
    if not resume_of:
        return None, set()
    if not (isinstance(resume_of, str) and re.fullmatch(r"[0-9a-f]{32}", resume_of)):
        raise ValueError("resume_of")
    pairs = [p.split(":") for p in (skip or "").split(",") if p]
    return resume_of, {(int(f), int(p)) for f, p in pairs}


@router.post("/uploads", status_code=202)
async def create_upload(request: Request, idempotency_key: str | None = Header(None)):
    """מקבלת קבצים (files) ומתחילה עיבוד ברקע; המשך העלאה: resume_of ו-skip (קובץ:עמוד מופרדים בפסיק)."""
    if idempotency_key and (job := pipeline.find_by_key(idempotency_key)):
        return job.snapshot()
    size = request.headers.get("content-length", "")
    if not size.isdigit():
        raise HTTPException(411, "חסר גודל הבקשה.")
    if int(size) > pipeline.MAX_TOTAL_BYTES + pipeline.MB:
        raise HTTPException(413, f"ההעלאה גדולה מ-{pipeline.MAX_TOTAL_BYTES // pipeline.MB}MB.")
    try:
        form = await request.form(max_files=pipeline.MAX_FILES + 1, max_fields=10)
        files = [await f.read() for f in form.getlist("files") if isinstance(f, UploadFile)]
        resume_of, skip = _parse_resume(form.get("resume_of"), form.get("skip"))
        await form.close()
    except Exception:
        raise HTTPException(400, "לא ניתן לקרוא את ההעלאה.") from None
    try:
        db.cleanup_demo()
        if resume_of:
            db.delete_quota_failures(resume_of)
    except Exception as e:
        log.warning("cleanup failed (%s)", type(e).__name__)
    try:
        job = pipeline.start_job(files, build_extractor, idempotency_key, on_result=db.save_page,
                                 batch_id=resume_of, skip=skip)
    except pipeline.UploadRejected as e:
        raise HTTPException(413, str(e)) from None
    except ExtractionError as e:
        raise HTTPException(503, e.message) from None
    return job.snapshot()


@router.get("/uploads/{job_id}")
def get_upload(job_id: str):
    """מחזירה התקדמות ורשומות שכבר מוכנות."""
    return _job_or_404(job_id).snapshot()


@router.post("/uploads/{job_id}/cancel")
def cancel_upload(job_id: str):
    """מפסיקה את העיבוד אחרי העמוד הנוכחי."""
    job = _job_or_404(job_id)
    job.cancel.set()
    return job.snapshot()


# ---------- רשומות ----------

class ValueIn(BaseModel):
    value: str | None = None


class NumberIn(BaseModel):
    kind: str
    value: str


def _call(fn, *args):
    """מריצה פעולת מסד ומתרגמת שגיאת רשומה ל-HTTP בעברית."""
    try:
        return fn(*args)
    except db.RecordError as e:
        raise HTTPException(e.status, e.message) from None


@router.get("/senders")
def list_senders():
    """הרשימה הסגורה של הגורמים השולחים: שם מלא (נשמר במסד, להשלמה בתיקון) ושם קצר לתצוגה בטבלה."""
    return [{"name": s, "short": short_sender_name(s)} for s in SENDERS]


@router.get("/commitments")
def list_commitments(q: str | None = None, sender: str | None = None, state: str | None = None,
                     needs_review: bool | None = None, batch_id: str | None = None,
                     limit: int = Query(50, ge=1, le=EXPORT_MAX), offset: int = Query(0, ge=0)):
    """רשימת רשומות עם חיפוש וסינון, וספירה של ממתין / אושר / נכשל."""
    return db.list_commitments(q, sender, state, needs_review, batch_id, limit, offset)


@router.get("/commitments/export")
def export_commitments(q: str | None = None, sender: str | None = None, state: str | None = None,
                       needs_review: bool | None = None, batch_id: str | None = None):
    """קובץ אקסל של הרשומות לפי אותו חיפוש וסינון (עמודים שנכשלו אינם התחייבויות ולא נכללים)."""
    data = db.list_commitments(q, sender, state, needs_review, batch_id, limit=EXPORT_MAX)
    items = [c for c in data["items"] if c["state"] != "failed"]
    log.info("export %d commitments", len(items))
    name = f"medextract-{datetime.now(export.LOCAL_TZ):%Y-%m-%d}.xlsx"
    return Response(export.to_xlsx(items), media_type=XLSX_TYPE,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/commitments/{record_id}")
def get_commitment(record_id: str):
    """רשומה אחת."""
    return _call(db.get_commitment, record_id)


@router.delete("/commitments/{record_id}", status_code=204)
def delete_commitment(record_id: str):
    """מחיקת רשומה מיותרת."""
    _call(db.delete_commitment, record_id)


@router.patch("/commitments/{record_id}/fields/{field}")
def correct_field(record_id: str, field: str, body: ValueIn):
    """תיקון שדה בודד (הערך החדש נבדק בקוד)."""
    return _call(db.correct_field, record_id, field, body.value)


@router.post("/commitments/{record_id}/fields/{field}/confirm")
def confirm_field(record_id: str, field: str):
    """אישור שדה בודד: הבודקת אישרה שהערך נכון."""
    return _call(db.confirm_field, record_id, field)


@router.post("/commitments/{record_id}/numbers/{number_id}/confirm")
def confirm_number(record_id: str, number_id: int):
    """אישור מספר בודד."""
    return _call(db.confirm_number, record_id, number_id)


@router.post("/commitments/{record_id}/numbers")
def add_number(record_id: str, body: NumberIn):
    """הוספת מספר מרכזי או מספר התחייבות."""
    return _call(db.add_number, record_id, body.kind, body.value)


@router.patch("/commitments/{record_id}/numbers/{number_id}")
def correct_number(record_id: str, number_id: int, body: ValueIn):
    """תיקון מספר קיים."""
    return _call(db.correct_number, record_id, number_id, body.value)


@router.delete("/commitments/{record_id}/numbers/{number_id}")
def delete_number(record_id: str, number_id: int):
    """מחיקת מספר שגוי."""
    return _call(db.delete_number, record_id, number_id)


@router.post("/commitments/{record_id}/approve")
def approve(record_id: str):
    """אישור רשומה."""
    return _call(db.approve, record_id)


@router.post("/commitments/approve-safe")
def approve_safe(batch_id: str | None = None):
    """אישור יחד של כל הרשומות הממתינות שכל השדות בהן תקינים."""
    return {"approved": db.approve_safe(batch_id)}
