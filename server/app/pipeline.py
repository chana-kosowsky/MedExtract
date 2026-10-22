import io
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

import pymupdf
from PIL import Image, ImageOps
from pydantic import BaseModel

from .barcodes import Barcode, read_barcodes, reconcile
from .extractor import ExtractionError, FieldExtractor
from .schema import ExtractedForm

log = logging.getLogger("medextract")

MB = 1024 * 1024
MAX_PAGES = 30
MAX_FILES = 30
MAX_FILE_BYTES = 20 * MB
MAX_TOTAL_BYTES = 50 * MB
DPI = 200
RETRY_WAITS = [10, 20, 40]
RETRYABLE = {"quota", "busy", "timeout", "network", "bad_json"}
MIN_INTERVAL = 4.0  # Lite: 15 בקשות בדקה
MAX_JOBS_KEPT = 50
BLANK_DARK_SHARE = 0.001


class UploadRejected(Exception):
    """העלאה שנדחתה כולה לפני עיבוד (תקרות). ההודעה בעברית."""


class Cancelled(Exception):
    """המשתמשת הפסיקה את העיבוד."""


class JobState(str, Enum):
    running = "running"
    done = "done"
    cancelled = "cancelled"
    quota_stopped = "quota_stopped"
    error = "error"


class PageResult(BaseModel):
    """תוצאה של עמוד אחד: רשומה, או כשל טכני עם קוד והודעה."""
    file_index: int
    page: int
    ok: bool
    form: ExtractedForm | None = None
    error_code: str | None = None
    error_message: str | None = None
    record_id: str | None = None
    save_error: str | None = None


@dataclass
class Job:
    id: str
    total_pages: int
    state: JobState = JobState.running
    message: str | None = None
    results: list[PageResult] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    on_result: Callable[[str, PageResult], str] | None = None
    batch_id: str = ""
    skip: set[tuple[int, int]] = field(default_factory=set)

    def __post_init__(self):
        self.batch_id = self.batch_id or self.id

    def snapshot(self) -> dict:
        """מצב העבודה כפי שהוא מוחזר ללקוח."""
        results = list(self.results)
        ok = sum(r.ok for r in results)
        return {
            "id": self.id,
            "batch_id": self.batch_id,
            "state": self.state.value,
            "message": self.message,
            "total_pages": self.total_pages,
            "processed": len(results),
            "succeeded": ok,
            "failed": len(results) - ok,
            "elapsed_seconds": round((self.finished or time.monotonic()) - self.started, 1),
            "results": [r.model_dump(mode="json") for r in results],
        }


# ---------- קלט ----------

def sniff(data: bytes) -> str | None:
    """מזהה את סוג הקובץ לפי התוכן, לא לפי הסיומת."""
    if b"%PDF" in data[:1024]:
        return "pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def count_pages(data: bytes) -> int:
    """סופרת עמודים; קובץ פגום או לא נתמך נספר כעמוד אחד שייכשל בעיבוד."""
    if sniff(data) != "pdf":
        return 1
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return max(doc.page_count, 1)
    except Exception:
        return 1


def check_limits(files: list[bytes], skip: set[tuple[int, int]] = frozenset()) -> int:
    """בודקת את תקרות הקבצים, הגודל והעמודים, ומחזירה את מספר העמודים לעיבוד (בלי המדולגים)."""
    if not files:
        raise UploadRejected("לא נבחרו קבצים.")
    if len(files) > MAX_FILES:
        raise UploadRejected(f"אפשר להעלות עד {MAX_FILES} קבצים בפעם אחת.")
    if any(len(d) > MAX_FILE_BYTES for d in files):
        raise UploadRejected(f"קובץ גדול מ-{MAX_FILE_BYTES // MB}MB.")
    if sum(len(d) for d in files) > MAX_TOTAL_BYTES:
        raise UploadRejected(f"ההעלאה גדולה מ-{MAX_TOTAL_BYTES // MB}MB.")
    counts = [count_pages(d) for d in files]
    skipped = sum(1 for fi, page in skip if 1 <= fi <= len(files) and 1 <= page <= counts[fi - 1])
    total = sum(counts) - skipped
    if total > MAX_PAGES:
        raise UploadRejected(f"בהעלאה יש {total} עמודים. המקסימום הוא {MAX_PAGES}.")
    if total == 0:
        raise UploadRejected("אין עמודים שנותרו לעיבוד.")
    return total


def check_not_blank(img: Image.Image) -> None:
    """עמוד כמעט כולו לבן לא נשלח למודל (חוסך מכסה)."""
    small = img.convert("L")
    small.thumbnail((600, 600))
    dark = sum(small.histogram()[:200])
    if dark / (small.width * small.height) < BLANK_DARK_SHARE:
        raise ExtractionError("empty_page", "העמוד ריק.")


def _free_pdf_cache() -> None:
    """מרוקנת את המטמון של PyMuPDF (תמונות סרוקות שפוענחו). בלי זה הוא גדל בכ-25MB לעמוד, והשרת בענן (512MB) קרס."""
    pymupdf.TOOLS.store_shrink(100)


def render_pdf_page(doc: pymupdf.Document, index: int) -> tuple[bytes, str]:
    """ממירה עמוד PDF לתמונת PNG בזיכרון."""
    try:
        pix = doc[index].get_pixmap(dpi=DPI)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    except Exception:
        raise ExtractionError("bad_page", "העמוד פגום ולא ניתן לקרוא אותו.") from None
    finally:
        _free_pdf_cache()
    check_not_blank(img)
    return pix.tobytes("png"), "image/png"


BARCODE_DPI = 300  # ברקודים דקים (Code 39 של מספרי התחייבות) לא נקראים ב-200 DPI. נמדד על 22 עמודים.


def pdf_barcodes(doc: pymupdf.Document, index: int) -> list[Barcode]:
    """קוראת את הברקודים בעמוד PDF מציור נפרד ברזולוציה גבוהה (התמונה למודל לא משתנה). בזיכרון בלבד."""
    try:
        pix = doc[index].get_pixmap(dpi=BARCODE_DPI)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    except Exception:
        return []
    finally:
        _free_pdf_cache()
    return read_barcodes(img)


def prepare_photo(data: bytes) -> tuple[bytes, str]:
    """פותחת תמונה, מיישרת לפי EXIF ומחזירה JPEG בזיכרון."""
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except Exception:
        raise ExtractionError("bad_file", "התמונה פגומה ולא ניתן לפתוח אותה.") from None
    check_not_blank(img)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue(), "image/jpeg"


def _fail(code: str, message: str):
    """מחזירה פונקציית הכנה שתמיד נכשלת (לקובץ שלא נפתח)."""
    def prepare():
        raise ExtractionError(code, message)
    return prepare


def iter_pages(files: list[bytes]):
    """עוברת על כל העמודים בכל הקבצים: (מספר קובץ, עמוד, הכנת התמונה, קריאת ברקודים או None לקריאה מהתמונה)."""
    for fi, data in enumerate(files, 1):
        kind = sniff(data)
        if kind is None:
            yield fi, 1, _fail("bad_type", "סוג קובץ לא נתמך. אפשר להעלות PDF, JPEG, PNG או WebP."), None
        elif kind != "pdf":
            yield fi, 1, lambda data=data: prepare_photo(data), None
        else:
            try:
                doc = pymupdf.open(stream=data, filetype="pdf")
            except Exception:
                yield fi, 1, _fail("bad_file", "הקובץ פגום ולא ניתן לפתוח אותו."), None
                continue
            with doc:
                if doc.page_count == 0:
                    yield fi, 1, _fail("bad_file", "בקובץ אין עמודים."), None
                for i in range(doc.page_count):
                    yield fi, i + 1, lambda i=i: render_pdf_page(doc, i), lambda i=i: pdf_barcodes(doc, i)


# ---------- עיבוד ----------

_rate_lock = threading.Lock()
_last_call = 0.0


def _wait_turn(cancel: threading.Event) -> None:
    """שומרת על מרווח מינימלי בין בקשות למודל, בכל העבודות יחד."""
    global _last_call
    with _rate_lock:
        delay = _last_call + MIN_INTERVAL - time.monotonic()
        if delay > 0 and cancel.wait(delay):
            raise Cancelled()
        _last_call = time.monotonic()


def extract_with_retry(extractor: FieldExtractor, image: bytes, mime: str, page: int,
                       cancel: threading.Event) -> ExtractedForm:
    """שולחת עמוד למודל, עם ניסיון חוזר והמתנה מתארכת בשגיאות זמניות."""
    for attempt, wait in enumerate(RETRY_WAITS + [None]):
        _wait_turn(cancel)
        try:
            return extractor.extract(image, mime, source_page=page)
        except ExtractionError as e:
            if wait is None or e.code not in RETRYABLE or (e.code == "bad_json" and attempt >= 1):
                raise
            log.info("retry code=%s attempt=%d wait=%ds", e.code, attempt + 1, wait)
            if cancel.wait(wait):
                raise Cancelled() from None


def extract_page(extractor: FieldExtractor, image: bytes, mime: str, page: int,
                 cancel: threading.Event, scan=None) -> ExtractedForm:
    """קריאת עמוד במודל, ואז הצלבת המספרים עם הברקודים שבעמוד (מקומית, בלי מודל).
    scan: קריאת ברקודים ברזולוציה גבוהה (עמוד PDF); בלעדיה הברקודים נקראים מהתמונה שנשלחה למודל."""
    form = extract_with_retry(extractor, image, mime, page, cancel)
    return reconcile(form, scan() if scan else read_barcodes(image))


def _failed(fi: int, page: int, e: ExtractionError) -> PageResult:
    """רשומת כשל טכני לעמוד."""
    return PageResult(file_index=fi, page=page, ok=False, error_code=e.code, error_message=e.message)


def _store(job: Job, result: PageResult) -> None:
    """שומרת את תוצאת העמוד (במסד) ומוסיפה אותה להתקדמות; כשל בשמירה לא עוצר."""
    if job.on_result:
        try:
            result.record_id = job.on_result(job.batch_id, result)
        except Exception as e:
            log.error("job=%s save failed (%s)", job.id, type(e).__name__)
            result.save_error = "העמוד עובד אבל לא נשמר במסד הנתונים."
    job.results.append(result)


def run_job(job: Job, files: list[bytes], extractor: FieldExtractor) -> None:
    """מעבדת את כל העמודים לפי הסדר; כשל בעמוד לא עוצר את השאר."""
    quota_error = None
    try:
        for fi, page, prepare, scan in iter_pages(files):
            if (fi, page) in job.skip:
                continue
            if job.cancel.is_set():
                break
            if quota_error:
                _store(job, _failed(fi, page, quota_error))
                continue
            start = time.perf_counter()
            try:
                image, mime = prepare()
                result = PageResult(file_index=fi, page=page, ok=True,
                                    form=extract_page(extractor, image, mime, page, job.cancel, scan))
            except Cancelled:
                break
            except ExtractionError as e:
                if e.code == "quota":
                    quota_error = e
                result = _failed(fi, page, e)
            image = None
            _store(job, result)
            log.info("job=%s page=%d/%d ok=%s code=%s %.1fs", job.id, len(job.results),
                     job.total_pages, result.ok, result.error_code, time.perf_counter() - start)
    except Exception as e:
        log.error("job=%s unexpected error (%s)", job.id, type(e).__name__)
        job.state, job.message = JobState.error, "שגיאה פנימית בעיבוד. העמודים שעובדו נשמרו."
    finally:
        files.clear()
        job.finished = time.monotonic()

    if job.state == JobState.error:
        return
    ok = sum(r.ok for r in job.results)
    if job.cancel.is_set():
        job.state, job.message = JobState.cancelled, f"העיבוד הופסק. {ok} עמודים עובדו."
    elif quota_error:
        job.state = JobState.quota_stopped
        job.message = "מכסת הבקשות למודל נגמרה. העמודים שלא עובדו מסומנים 'לא עבד'. אפשר לנסות שוב מאוחר יותר."
    else:
        job.state = JobState.done
        job.message = f"הסתיים: {ok} עמודים עובדו, {len(job.results) - ok} נכשלו."


# ---------- ניהול עבודות (ההתקדמות בזיכרון; הרשומות נשמרות במסד דרך on_result) ----------

_jobs: dict[str, Job] = {}
_keys: dict[str, str] = {}
_jobs_lock = threading.Lock()


def _forget_old_jobs() -> None:
    """שומרת רק את העבודות האחרונות בזיכרון."""
    for jid in list(_jobs)[:-MAX_JOBS_KEPT]:
        if _jobs[jid].state != JobState.running:
            del _jobs[jid]
    for key in [k for k, jid in _keys.items() if jid not in _jobs]:
        del _keys[key]


def find_by_key(key: str) -> Job | None:
    """מחזירה עבודה קיימת לפי מפתח אידמפוטנטיות."""
    with _jobs_lock:
        return _jobs.get(_keys.get(key, ""))


def get_job(job_id: str) -> Job | None:
    """מחזירה עבודה לפי מזהה."""
    return _jobs.get(job_id)


def start_job(files: list[bytes], make_extractor, key: str | None = None, on_result=None,
              batch_id: str | None = None, skip: set[tuple[int, int]] = frozenset()) -> Job:
    """יוצרת עבודה ברקע (או המשך: batch_id מקורי ו-skip של עמודים שעובדו); אותו מפתח = אותה עבודה."""
    with _jobs_lock:
        if key and key in _keys and _keys[key] in _jobs:
            return _jobs[_keys[key]]
        total = check_limits(files, skip)
        extractor = make_extractor()
        job = Job(id=uuid.uuid4().hex, total_pages=total, on_result=on_result,
                  batch_id=batch_id or "", skip=set(skip))
        _jobs[job.id] = job
        if key:
            _keys[key] = job.id
        _forget_old_jobs()
    threading.Thread(target=run_job, args=(job, files, extractor), daemon=True).start()
    return job
