import io
import threading
import time

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import pipeline, routes
from app.extractor import ExtractionError, FieldExtractor
from app.main import app
from app.schema import ModelField, ModelOutput


class FakeExtractor(FieldExtractor):
    """מחלץ מדומה: בלי Gemini. מחזיר רשומה ריקה, או שגיאות לפי תסריט."""

    def __init__(self, errors=None, delay=0.0):
        self.errors = list(errors or [])
        self.delay = delay
        self.calls = []

    def read_page(self, image, mime_type):
        """מחזירה תשובה ריקה, או זורקת את השגיאה הבאה בתסריט."""
        self.calls.append(mime_type)
        time.sleep(self.delay)
        if self.errors:
            raise self.errors.pop(0)
        empty = ModelField()
        return ModelOutput(first_name=empty, last_name=empty, id_number=empty, sender=empty,
                           received_date_stamp=empty, received_date_handwritten=empty)


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    """בלי המתנות אמיתיות בבדיקות."""
    monkeypatch.setattr(pipeline, "MIN_INTERVAL", 0)
    monkeypatch.setattr(pipeline, "RETRY_WAITS", [0, 0, 0])


def make_pdf(pages: list[str]) -> bytes:
    """יוצרת PDF: 'form' = עמוד עם תוכן, 'blank' = עמוד ריק."""
    doc = pymupdf.open()
    for kind in pages:
        page = doc.new_page()
        if kind == "form":
            page.draw_rect(pymupdf.Rect(50, 50, 300, 200), fill=(0, 0, 0))
    return doc.tobytes()


def test_pdf_cache_emptied_after_each_page(monkeypatch):
    """אחרי כל ציור וכל קריאת ברקודים המטמון של PyMuPDF מתרוקן (נמדד: 360MB בלי זה, 128MB עם), גם בעמוד ריק."""
    shrinks = []
    monkeypatch.setattr(pymupdf.TOOLS, "store_shrink", lambda pct: shrinks.append(pct))
    doc = pymupdf.open(stream=make_pdf(["form", "blank"]), filetype="pdf")
    pipeline.render_pdf_page(doc, 0)
    pipeline.pdf_barcodes(doc, 0)
    with pytest.raises(ExtractionError):
        pipeline.render_pdf_page(doc, 1)
    assert shrinks == [100, 100, 100]


def make_photo(rotated: bool) -> bytes:
    """יוצרת JPEG לרוחב, עם תג EXIF שאומר לסובב אותו (כמו מהטלפון)."""
    img = Image.new("RGB", (400, 200), "white")
    img.paste((0, 0, 0), (0, 0, 100, 100))
    exif = Image.Exif()
    if rotated:
        exif[0x0112] = 6
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif)
    return out.getvalue()


def run(files, extractor=None) -> pipeline.Job:
    """מריצה עבודה בלי חוט רקע ומחזירה אותה."""
    job = pipeline.Job(id="t", total_pages=pipeline.check_limits(files))
    pipeline.run_job(job, list(files), extractor or FakeExtractor())
    return job


def test_pdf_with_blank_and_broken_pages(monkeypatch):
    """עמוד פגום ועמוד ריק מסומנים 'נכשל' והשאר ממשיכים."""
    real = pipeline.render_pdf_page

    def render(doc, index):
        if index == 1:
            raise ExtractionError("bad_page", "העמוד פגום ולא ניתן לקרוא אותו.")
        return real(doc, index)

    monkeypatch.setattr(pipeline, "render_pdf_page", render)
    ex = FakeExtractor()
    job = run([make_pdf(["form", "form", "blank", "form"])], ex)
    assert job.state == pipeline.JobState.done
    assert [(r.page, r.ok, r.error_code) for r in job.results] == [
        (1, True, None), (2, False, "bad_page"), (3, False, "empty_page"), (4, True, None)]
    assert len(ex.calls) == 2
    assert job.results[3].form.source_page == 4


def test_pdf_barcodes_read_at_high_resolution():
    """בעמוד PDF הברקודים נקראים מציור נפרד ב-300 DPI: ברקוד דק שלא נקרא בתמונה שנשלחת למודל (200 DPI)."""
    import zxingcpp

    code = Image.fromarray(zxingcpp.write_barcode(zxingcpp.BarcodeFormat.Code39, "7254647", width=0, height=40))
    buf = io.BytesIO()
    code.save(buf, "PNG")
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(50, 50, 300, 200), fill=(0, 0, 0))  # שהעמוד לא ייחשב ריק
    # פס צר של חצי נקודה: כ-1.4 פיקסלים ב-200 DPI (לא נקרא), כ-2 ב-300 DPI (נקרא)
    page.insert_image(pymupdf.Rect(100, 600, 100 + code.width * 0.5, 640), stream=buf.getvalue())
    with pymupdf.open(stream=doc.tobytes(), filetype="pdf") as pdf:
        image, _ = pipeline.render_pdf_page(pdf, 0)
        assert "7254647" not in {b.text for b in pipeline.read_barcodes(image)}  # ב-200 DPI: לא נקרא
        assert "7254647" in {b.text for b in pipeline.pdf_barcodes(pdf, 0)}       # ב-300 DPI: נקרא


def test_run_job_uses_high_resolution_barcodes(monkeypatch):
    """הצינור משתמש בברקודים מהציור ברזולוציה הגבוהה לעמודי PDF, ומהתמונה עצמה לתמונות."""
    used = []
    monkeypatch.setattr(pipeline, "pdf_barcodes", lambda doc, i: used.append("pdf") or [])
    real = pipeline.read_barcodes
    monkeypatch.setattr(pipeline, "read_barcodes", lambda img: used.append("image") or real(img))
    run([make_pdf(["form"]), make_photo(False)])
    assert used == ["pdf", "image"]


def test_broken_and_unsupported_files_do_not_stop_others():
    """קובץ פגום וקובץ מסוג לא נתמך לא עוצרים את הקבצים האחרים."""
    job = run([b"%PDF-1.4 garbage", b"plain text", make_pdf(["form"]), b"\xff\xd8\xff broken"])
    assert [(r.file_index, r.ok, r.error_code) for r in job.results] == [
        (1, False, "bad_file"), (2, False, "bad_type"), (3, True, None), (4, False, "bad_file")]
    assert "1 עמודים עובדו, 3 נכשלו" in job.message


def test_photo_exif_rotation(monkeypatch):
    """תמונה עם תג סיבוב מיושרת לפני השליחה למודל."""
    sent = {}
    monkeypatch.setattr(FakeExtractor, "extract",
                        lambda self, image, mime, source_page=None: sent.update(img=image, mime=mime))
    run([make_photo(rotated=True)])
    img = Image.open(io.BytesIO(sent["img"]))
    assert sent["mime"] == "image/jpeg"
    assert img.size == (200, 400)


def test_limits():
    """תקרות עמודים, קבצים וגודל נבדקות בשרת."""
    with pytest.raises(pipeline.UploadRejected, match="31 עמודים"):
        pipeline.check_limits([make_pdf(["form"] * 31)])
    with pytest.raises(pipeline.UploadRejected, match="קבצים"):
        pipeline.check_limits([b"x"] * 31)
    with pytest.raises(pipeline.UploadRejected, match="20MB"):
        pipeline.check_limits([b"x" * (pipeline.MAX_FILE_BYTES + 1)])
    with pytest.raises(pipeline.UploadRejected):
        pipeline.check_limits([])


def test_retry_then_success():
    """שגיאה זמנית (עומס, מכסה לדקה) עוברת אחרי ניסיון חוזר."""
    ex = FakeExtractor(errors=[ExtractionError("busy", "עמוס"), ExtractionError("quota", "מכסה")])
    job = run([make_pdf(["form"])], ex)
    assert job.results[0].ok
    assert len(ex.calls) == 3


def test_bad_json_retried_once():
    """תשובה לא תקינה מקבלת ניסיון חוזר אחד בלבד."""
    ex = FakeExtractor(errors=[ExtractionError("bad_json", "לא תקינה")] * 3)
    job = run([make_pdf(["form"])], ex)
    assert job.results[0].error_code == "bad_json"
    assert len(ex.calls) == 2


def test_quota_exhausted_stops_and_marks_rest():
    """מכסה שנגמרה: לא ממשיכים לפנות למודל, והעמודים שנשארו מסומנים 'לא עבד'."""
    ex = FakeExtractor(errors=[ExtractionError("quota", "נגמרה מכסת הבקשות")] * 10)
    job = run([make_pdf(["form", "form", "form"])], ex)
    assert job.state == pipeline.JobState.quota_stopped
    assert [r.error_code for r in job.results] == ["quota"] * 3
    assert len(ex.calls) == 4
    assert "מכסת" in job.message


def test_cancel_midway():
    """הפסקה באמצע: העמודים שעובדו נשארים, השאר לא מעובדים."""
    ex = FakeExtractor(delay=0.2)
    job = pipeline.Job(id="c", total_pages=5)
    t = threading.Thread(target=pipeline.run_job, args=(job, [make_pdf(["form"] * 5)], ex))
    t.start()
    time.sleep(0.3)
    job.cancel.set()
    t.join(5)
    assert job.state == pipeline.JobState.cancelled
    assert 1 <= len(job.results) < 5


def test_upload_api_end_to_end(monkeypatch):
    """העלאה דרך ה-API: התקדמות עד הסוף, ומפתח כפול לא מעבד שוב."""
    ex = FakeExtractor()
    monkeypatch.setattr(routes, "build_extractor", lambda: ex)
    client = TestClient(app)
    files = [("files", ("a.pdf", make_pdf(["form", "form"]), "application/pdf")),
             ("files", ("b.jpg", make_photo(rotated=False), "image/jpeg"))]
    r = client.post("/api/uploads", files=files, headers={"Idempotency-Key": "k1"})
    assert r.status_code == 202
    job_id = r.json()["id"]
    for _ in range(100):
        body = client.get(f"/api/uploads/{job_id}").json()
        if body["state"] != "running":
            break
        time.sleep(0.05)
    assert body["state"] == "done"
    assert body["total_pages"] == 3 and body["succeeded"] == 3
    assert all(r["record_id"] for r in body["results"])
    saved = client.get("/api/commitments", params={"batch_id": job_id}).json()
    assert saved["total"] == 3

    again = client.post("/api/uploads", files=files, headers={"Idempotency-Key": "k1"})
    assert again.json()["id"] == job_id
    assert len(ex.calls) == 3


def test_resume_skips_done_pages_and_keeps_batch():
    """המשך העלאה: מדלג על עמודים שעובדו, שומר תחת אותה העלאה ובמספרי העמודים המקוריים."""
    saved = []
    ex = FakeExtractor()
    files = [make_pdf(["form"] * 4)]
    job = pipeline.Job(id="r2", total_pages=pipeline.check_limits(files, {(1, 1), (1, 2)}),
                       batch_id="orig", skip={(1, 1), (1, 2)},
                       on_result=lambda batch, r: saved.append((batch, r.page)) or "id")
    pipeline.run_job(job, list(files), ex)
    assert job.total_pages == 2
    assert [r.page for r in job.results] == [3, 4]
    assert saved == [("orig", 3), ("orig", 4)]
    assert len(ex.calls) == 2


def test_resume_with_nothing_left_is_rejected():
    """המשך כשכל העמודים כבר עובדו נדחה בהודעה בעברית."""
    with pytest.raises(pipeline.UploadRejected, match="אין עמודים"):
        pipeline.check_limits([make_pdf(["form"])], {(1, 1)})


def test_resume_api_replaces_quota_failures(monkeypatch):
    """המשך דרך ה-API אחרי מכסה: עמוד 'נכשל' בגלל מכסה נמחק ומעובד מחדש, בלי כפילות."""
    from app import db

    quota = FakeExtractor(errors=[ExtractionError("quota", "נגמרה מכסת הבקשות")] * 10)
    monkeypatch.setattr(routes, "build_extractor", lambda: quota)
    client = TestClient(app)
    pdf = make_pdf(["form", "form"])
    first = client.post("/api/uploads", files=[("files", ("a.pdf", pdf, "application/pdf"))]).json()
    for _ in range(100):
        first = client.get(f"/api/uploads/{first['id']}").json()
        if first["state"] != "running":
            break
        time.sleep(0.05)
    assert first["state"] == "quota_stopped"
    batch = first["batch_id"]
    assert db.list_commitments(batch_id=batch)["counts"]["failed"] == 2

    monkeypatch.setattr(routes, "build_extractor", FakeExtractor)
    second = client.post("/api/uploads", files=[("files", ("a.pdf", pdf, "application/pdf"))],
                         data={"resume_of": batch, "skip": ""}).json()
    assert second["batch_id"] == batch and second["total_pages"] == 2
    for _ in range(100):
        second = client.get(f"/api/uploads/{second['id']}").json()
        if second["state"] != "running":
            break
        time.sleep(0.05)
    counts = db.list_commitments(batch_id=batch)
    assert counts["total"] == 2 and counts["counts"]["failed"] == 0


def test_resume_bad_batch_id_rejected():
    """מזהה המשך לא תקין נדחה."""
    client = TestClient(app)
    r = client.post("/api/uploads", files=[("files", ("a.pdf", make_pdf(["form"]), "application/pdf"))],
                    data={"resume_of": "../etc"})
    assert r.status_code == 400


def test_save_failure_does_not_stop_job():
    """כשל בשמירה למסד מסומן בעמוד, והעיבוד ממשיך."""
    def broken_save(job_id, result):
        raise ConnectionError()

    job = pipeline.Job(id="s", total_pages=2, on_result=broken_save)
    pipeline.run_job(job, [make_pdf(["form", "form"])], FakeExtractor())
    assert job.state == pipeline.JobState.done
    assert [r.save_error is not None for r in job.results] == [True, True]


def test_upload_api_errors(monkeypatch):
    """עבודה לא קיימת והעלאה מעל התקרה מחזירות הודעה בעברית."""
    monkeypatch.setattr(routes, "build_extractor", FakeExtractor)
    client = TestClient(app)
    assert client.get("/api/uploads/nope").json()["detail"] == "העבודה לא נמצאה."
    r = client.post("/api/uploads", files=[("files", ("a.pdf", make_pdf(["form"] * 31), "application/pdf"))])
    assert r.status_code == 413
    assert "31 עמודים" in r.json()["detail"]


def test_upload_stays_in_memory():
    """קבצים עד התקרה לא נכתבים לקובץ זמני בדיסק."""
    assert routes.MultiPartParser.max_file_size >= pipeline.MAX_TOTAL_BYTES
