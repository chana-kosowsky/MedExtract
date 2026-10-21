import pytest
from google.genai import errors

from app import extractor as ext
from app.extractor import ChainExtractor, ExtractionError, FieldExtractor, GeminiExtractor, build_extractor
from app.schema import FieldStatus, ModelField, ModelOutput


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeModels:
    def __init__(self, result):
        self.result = result

    def generate_content(self, **kwargs):
        """מחזירה תשובה קבועה או זורקת שגיאה, במקום לפנות ל-Gemini."""
        if isinstance(self.result, Exception):
            raise self.result
        return FakeResponse(self.result)


class FakeClient:
    def __init__(self, result):
        self.models = FakeModels(result)


def make_extractor(monkeypatch, result) -> GeminiExtractor:
    """יוצרת GeminiExtractor עם מפתח מזויף ולקוח מזויף."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("GEMINI_MODEL", "fake-model")
    ex = GeminiExtractor()
    ex._client = FakeClient(result)
    return ex


def test_invalid_json(monkeypatch):
    """תשובה שאינה JSON הופכת לשגיאת bad_json עם הודעה בעברית."""
    ex = make_extractor(monkeypatch, "זו לא תשובת JSON")
    with pytest.raises(ExtractionError) as e:
        ex.extract(b"img", "image/png", source_page=1)
    assert e.value.code == "bad_json"
    assert "לא תקינה" in e.value.message


def test_quota_error(monkeypatch):
    """שגיאת 429 הופכת לשגיאת quota עם הודעה בעברית."""
    ex = make_extractor(monkeypatch, errors.APIError(429, {"error": {"message": "quota"}}))
    with pytest.raises(ExtractionError) as e:
        ex.extract(b"img", "image/png")
    assert e.value.code == "quota"
    assert "מכסת" in e.value.message


def test_valid_response(monkeypatch):
    """JSON תקין הופך לרשומה; שדה ריק מסומן not_found ולא מנוחש."""
    empty = '{"text": null, "confidence": 0}'
    body = (
        '{"page_rotation": 0,'
        f'"first_name": {empty}, "last_name": {empty},'
        '"id_number": {"text": "11223344", "confidence": 0.9},'
        '"central_numbers": [{"text": "947768", "confidence": 1, "label": "מרכזי"}],'
        f'"received_date_stamp": {empty}, "received_date_handwritten": {empty},'
        '"sender": {"text": "שניידר", "confidence": 0.9},'
        '"commitment_numbers": []}'
    )
    form = make_extractor(monkeypatch, body).extract(b"img", "image/png", source_page=2)
    assert form.source_page == 2
    assert form.first_name.status == FieldStatus.not_found
    assert form.first_name.value is None
    assert form.received_date.status == FieldStatus.not_found
    assert form.id_number.value == "11223344"
    assert [n.value for n in form.central_numbers] == ["947768"]
    assert form.model == "fake-model"


# ---------- שרשרת מודלים (החלטה 34) ----------

class Link(FieldExtractor):
    """מודל מדומה בשרשרת: מחזיר תשובה ריקה, או זורק את השגיאות שבתסריט לפי הסדר."""

    def __init__(self, name, errors=()):
        self.model, self.errors, self.calls = name, list(errors), 0

    def read_page(self, image, mime_type):
        self.calls += 1
        if self.errors:
            raise ExtractionError(self.errors.pop(0), "x")
        empty = ModelField()
        return ModelOutput(first_name=empty, last_name=empty, id_number=empty, sender=empty,
                           received_date_stamp=empty, received_date_handwritten=empty)


def test_chain_primary_used_when_it_works():
    """כשהראשי עובד, הגיבויים לא נקראים, והרשומה יודעת איזה מודל קרא אותה."""
    opus, flash, lite = Link("opus"), Link("flash"), Link("lite")
    form = ChainExtractor([opus, flash, lite]).extract(b"img", "image/png")
    assert form.model == "opus" and (flash.calls, lite.calls) == (0, 0)


def test_chain_primary_transient_failure_retried_next_page():
    """עומס בראשי: העמוד עובר לבא בתור, והעמוד הבא מנסה שוב את הראשי."""
    opus, flash = Link("opus", ["busy"]), Link("flash")
    chain = ChainExtractor([opus, flash, Link("lite")])
    assert chain.extract(b"img", "image/png").model == "flash"
    assert chain.extract(b"img", "image/png").model == "opus"


def test_chain_primary_permanent_failure_skipped():
    """קרדיט שנגמר או מפתח שגוי בראשי: מדלגים עליו עד סוף ההעלאה."""
    opus = Link("opus", ["api"])
    chain = ChainExtractor([opus, Link("flash"), Link("lite")])
    chain.extract(b"img", "image/png")
    assert chain.extract(b"img", "image/png").model == "flash" and opus.calls == 1


def test_chain_middle_skipped_after_one_failure():
    """3.8 Flash עמוס פעם אחת: העמוד עובר ל-Lite, ומדלגים על 3.8 עד סוף ההעלאה."""
    opus, flash, lite = Link("opus", ["busy", "busy"]), Link("flash", ["timeout"]), Link("lite")
    chain = ChainExtractor([opus, flash, lite])
    assert chain.extract(b"img", "image/png").model == "lite"
    assert chain.extract(b"img", "image/png").model == "lite" and flash.calls == 1


def test_chain_all_fail_raises_last_error():
    """כל המודלים נכשלו: השגיאה של האחרון עוברת לצינור (שם יש ניסיון חוזר)."""
    chain = ChainExtractor([Link("opus", ["busy"]), Link("flash", ["busy"]), Link("lite", ["quota"])])
    with pytest.raises(ExtractionError) as e:
        chain.extract(b"img", "image/png")
    assert e.value.code == "quota"


def test_build_chain_from_env(monkeypatch):
    """MODEL_CHAIN בונה שרשרת לפי הסדר; האמצעי מקבל זמן המתנה קצר; מודל בלי מפתח מדולג."""
    made = []

    def fake(name):
        def make(model, timeout):
            made.append((name, model, timeout))
            if name == "anthropic":
                raise ExtractionError("config", "no key")
            return Link(model)
        return make

    monkeypatch.setattr(ext, "PROVIDERS", {"anthropic": fake("anthropic"), "gemini": fake("gemini")})
    monkeypatch.setenv("MODEL_CHAIN", "anthropic:opus, gemini:flash, gemini:lite")
    chain = build_extractor()
    assert [m for _, m, _ in made] == ["opus", "flash", "lite"]
    assert made[1][2] == ext.MIDDLE_TIMEOUT and made[2][2] == ext.TIMEOUT_SECONDS
    assert [link.model for link in chain.links] == ["flash", "lite"]


def test_build_without_chain_uses_gemini_model(monkeypatch):
    """בלי MODEL_CHAIN: Gemini עם GEMINI_MODEL בלבד, כמו קודם."""
    monkeypatch.delenv("MODEL_CHAIN", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("GEMINI_MODEL", "fake-model")
    ex = build_extractor()
    assert isinstance(ex, GeminiExtractor) and ex.model == "fake-model"
