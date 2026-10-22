import base64
import json
import logging
import os
from abc import ABC, abstractmethod

from dotenv import load_dotenv
from pydantic import ValidationError

from .schema import ExtractedForm, ModelOutput
from .validation import SENDERS, build_form

load_dotenv()
log = logging.getLogger("medextract")

TIMEOUT_SECONDS = 90

PROMPT = """# ROLE
You are a meticulous data-entry specialist at Israel's Central Virology Laboratory.
You transcribe commitment forms (טופס התחייבות) that arrive with lab samples.

# OBJECTIVE
Extract 7 fields from ONE page image, exactly as written, and report how sure you are about each one.
A human lab technician will review every field you mark as uncertain.

# CONTEXT
- Forms come from HMOs and hospitals. They may be printed, scanned, photographed, handwritten, rotated, or partly cut off.
- The lab adds a barcode sticker labeled "מרכזי" (central number) and a "התקבל" (received) stamp.
- The Central Virology Laboratory / Tel HaShomer (תל השומר) is the RECIPIENT, never the sender.

# INPUT
One image of one page.

# INSTRUCTIONS
1. Patient: first_name, last_name, id_number belong to the PATIENT, not the doctor.
   Patient details are often written BY HAND in pen over or next to the printed patient fields (name, ת.ז / מ.ז).
   When a handwritten value overwrites or sits next to a printed one, the HANDWRITTEN value is the current one;
   the printed value underneath is obsolete - do not return it.
   Hospital sticker numbers are NOT the ID and NOT a commitment number: "מקרה" (case number), "מ.ר.",
   "מס' ביקור" are never id_number and never commitment_numbers.
   An address or city ("כתובת", "עיר", e.g. a village name) is NEVER a name.
   A name in a signature or stamp area ("חתימה", "חותמת", "חתימת הרופא", "חתימת עובד המעבדה", "שם הרופא",
   "אישור הנהלה", a doctor's or clerk's stamp) is NEVER the patient's name - ignore it.
   If the patient's name is handwritten and you cannot read it, return null with a reason.
   Do NOT return instead some other printed name found elsewhere on the page.
2. central_numbers: ONLY a number that has the word "מרכזי" PHYSICALLY RIGHT NEXT TO IT - usually printed
   vertically beside the barcode on the same small lab sticker (or the number handwritten right next to "מרכזי").
   If the word "מרכזי" is not touching THIS number, it is NOT a central number - even if "מרכזי" appears
   elsewhere on the page. Usually 6 digits, but the length can differ; do not use length to decide.
   A form usually carries ONE central sticker. If you found more than one, re-check each: return a number only if
   "מרכזי" is right beside it. Set `label` to the text you actually see beside the number - never write "מרכזי"
   as a label unless that word is really there.
   Other barcode stickers (the hospital's patient sticker, large barcodes, numbers at the top of the form)
   are NOT central numbers, even when they have no label - they are usually the commitment number.
   Some forms (printed computer screens) have a handwritten note like "25.8 - 947501": the 6-digit part is the
   central number and the "25.8" part is the received date. Never merge them into one number.
3. commitment_numbers: labeled "התחייבות" or "דרישה"; in Leumit (לאומית) forms also labeled "דגימה".
   Return ALL of them, with the label you saw in `label`. A number labeled "אסמכתא" is NOT a commitment number.
   A commitment number may start with one or two English letters (e.g. "A1234567"); copy the letters exactly as written.
   Commitment numbers often appear with NO label at all. If you believe a bare number is a commitment number,
   include it with label = null; do not skip it.
4. received_date_stamp: date from the lab's "התקבל" stamp ONLY.
   received_date_handwritten: the date handwritten by the lab next to or below the central number ONLY
   (including the "25.8 - 947501" pattern above).
   The hospital's own admission date ("ת.קבלה" on the patient sticker), the form date, birth date and
   sample-collection date are NOT the received date.
   Copy dates exactly as written. If the year is not written, return only day and month (e.g. "25.8") -
   NEVER add a year that is not on the page.
5. sender: the INSTITUTION that sent the sample, not a doctor or department.
   If both a hospital and an HMO (כללית / מכבי / מאוחדת / לאומית) appear, the sender is the HOSPITAL;
   the HMO only issues the commitment. A hospital may appear as its logo, or handwritten in a "בית החולים" field
   on an HMO's form template (e.g. a Clalit form with "השרון" written in it -> the sender is that hospital).
   Use an HMO only when no hospital appears on the form.
   On an HMO's commitment form, the "נותן השירות" / "ספק השירות" (service provider) box names the lab that
   PERFORMS the test - it is the RECIPIENT, never the sender. The Central Virology Laboratory is at Sheba
   (שיבא / תל השומר), so Sheba in that box is the recipient; the sender is then the HMO that issued the form.
   On printed computer screens, the paying party may be "תיירות מרפא" or "הרשות הפלסטינית" - these are on the list.
   Choose from:
{senders}
   If it is not on the list: write the name as it appears, low confidence, unclear_reason = "not in list".
6. page_rotation: 0 / 90 / 180 / 270.

# CONSTRAINTS
- Copy every value EXACTLY as written. Never correct, complete, or infer missing digits.
- Never guess. An empty field is better than a wrong one.
- NEVER produce a plausible-looking name. Do not fill in a common Hebrew name because it "fits" a few strokes.
- Ignore other dates (top of page, sample collection date).
- Do not return phone numbers, product barcodes, or non-central sticker numbers as commitment numbers.
- Ignore yellow highlighting; it is not meaningful.

# OUTPUT
JSON matching the provided schema. Hebrew values stay in Hebrew.
- text: exact text, or null if the field does not appear.
- confidence: 0-1, how sure you are the reading is correct character-by-character.
- unclear_reason: why you are unsure, written in HEBREW (e.g. "כתב יד לא ברור", "מדבקה חתוכה", "טשטוש", "דף מסובב").
- box_2d: where the value is written on the page, as [ymin, xmin, ymax, xmax] normalized to 0-1000
  (0,0 = top-left corner of the image), tightly around the value itself. null when text is null.

# EVALUATION
A good result: every digit and letter matches the page; every doubtful field has low confidence and a reason;
nothing is invented. A confident wrong value is the worst possible error.

# FAILURE HANDLING
- Field present but unreadable: give your best partial reading, confidence <= 0.3, explain why.
- Field absent: text = null.
- Page is not a commitment form, or is blank: all fields null, unclear_reason on sender = "not a commitment form".
"""


class ExtractionError(Exception):
    """כשל טכני בעמוד: קוד קצר ללוג, והודעה בעברית למשתמשת."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class FieldExtractor(ABC):
    """הממשק היחיד ששאר הקוד מכיר: תמונה של עמוד נכנסת, רשומה יוצאת."""

    model: str | None = None  # שם המודל שקרא את העמוד האחרון (למדידה בלבד, לא מוצג במסך)

    def extract(self, image: bytes, mime_type: str, source_page: int | None = None) -> ExtractedForm:
        """מחלצת את השדות מעמוד אחד ומחזירה רשומה סופית."""
        form = build_form(self.read_page(image, mime_type), source_page)
        form.model = self.model
        return form

    @abstractmethod
    def read_page(self, image: bytes, mime_type: str) -> ModelOutput:
        """שולחת את העמוד לספק ומחזירה את תשובת המודל אחרי ולידציה."""


class GeminiExtractor(FieldExtractor):
    """מימוש עם Gemini. המפתח ושם המודל נקראים מ-.env."""

    def __init__(self, model: str | None = None, media_resolution: str | None = None,
                 timeout: int = TIMEOUT_SECONDS):
        from google import genai
        from google.genai import types

        key = os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL")
        if not key or not self.model:
            raise ExtractionError("config", "חסר מפתח Gemini או שם מודל בהגדרות השרת")
        # רזולוציית הקריאה של התמונה במודל (low / medium / high); ריק = ברירת המחדל של Google
        level = (media_resolution or os.getenv("GEMINI_MEDIA_RESOLUTION") or "").strip().upper()
        if level and level not in ("LOW", "MEDIUM", "HIGH"):
            raise ExtractionError("config", "GEMINI_MEDIA_RESOLUTION צריך להיות low, medium או high")
        self.media_resolution = getattr(types.MediaResolution, f"MEDIA_RESOLUTION_{level}") if level else None
        self._types = types
        self._client = genai.Client(
            api_key=key, http_options=types.HttpOptions(timeout=timeout * 1000)
        )
        self._prompt = PROMPT.format(senders="\n".join(f"   - {s}" for s in SENDERS))

    def read_page(self, image: bytes, mime_type: str) -> ModelOutput:
        """שולחת עמוד ל-Gemini עם סכמת פלט, ומתרגמת כל כשל להודעה בעברית."""
        from google.genai import errors

        types = self._types
        try:
            resp = self._client.models.generate_content(
                model=self.model,
                contents=[types.Part.from_bytes(data=image, mime_type=mime_type), self._prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ModelOutput,
                    temperature=0,
                    media_resolution=self.media_resolution,
                ),
            )
        except errors.APIError as e:
            log.warning("gemini api error code=%s", e.code)
            if e.code == 429:
                raise ExtractionError("quota", "נגמרה מכסת הבקשות למודל. אפשר לנסות שוב מאוחר יותר.") from None
            if e.code in (500, 502, 503, 504):
                raise ExtractionError("busy", "שירות המודל עמוס כרגע.") from None
            raise ExtractionError("api", f"שגיאה בשירות המודל (קוד {e.code}).") from None
        except Exception as e:
            log.warning("gemini call failed (%s)", type(e).__name__)
            if "timeout" in type(e).__name__.lower():
                raise ExtractionError("timeout", "המודל לא ענה בזמן. אפשר לנסות שוב.") from None
            raise ExtractionError("network", "אין חיבור לשירות המודל.") from None

        try:
            return ModelOutput.model_validate_json(resp.text or "")
        except ValidationError:
            log.warning("gemini returned invalid json")
            raise ExtractionError("bad_json", "המודל החזיר תשובה לא תקינה לעמוד הזה.") from None


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


class AnthropicExtractor(FieldExtractor):
    """מימוש עם Claude (Anthropic). המפתח ושם המודל נקראים מ-.env."""

    def __init__(self, model: str | None = None, timeout: int = TIMEOUT_SECONDS):
        import httpx

        key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
        self.model = model or os.getenv("ANTHROPIC_MODEL")
        if not key or not self.model:
            raise ExtractionError("config", "חסר מפתח Claude או שם מודל בהגדרות השרת")
        self._client = httpx.Client(timeout=timeout, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01"})
        # הסכמה שלנו מורכבת מדי לפלט מובנה של Anthropic (שדות nullable רבים), ולכן היא נכתבת בפרומפט
        schema = json.dumps(ModelOutput.model_json_schema(), ensure_ascii=False)
        self._prompt = (PROMPT.format(senders="\n".join(f"   - {s}" for s in SENDERS))
                        + f"\nReturn ONLY a JSON object that follows this JSON schema, with no other text:\n{schema}\n")

    def read_page(self, image: bytes, mime_type: str) -> ModelOutput:
        """שולחת עמוד ל-Claude ומתרגמת כל כשל להודעה בעברית."""
        import httpx

        body = {
            "model": self.model,
            "max_tokens": 4000,  # בלי temperature: במודלים החדשים של Claude הפרמטר לא נתמך
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime_type,
                                             "data": base64.b64encode(image).decode()}},
                {"type": "text", "text": self._prompt},
            ]}],
        }
        try:
            resp = self._client.post(ANTHROPIC_URL, json=body)
        except httpx.TimeoutException:
            log.warning("anthropic call failed (timeout)")
            raise ExtractionError("timeout", "המודל לא ענה בזמן. אפשר לנסות שוב.") from None
        except httpx.HTTPError as e:
            log.warning("anthropic call failed (%s)", type(e).__name__)
            raise ExtractionError("network", "אין חיבור לשירות המודל.") from None
        if resp.status_code != 200:
            log.warning("anthropic api error code=%s", resp.status_code)
            if resp.status_code == 429:
                raise ExtractionError("quota", "נגמרה מכסת הבקשות למודל. אפשר לנסות שוב מאוחר יותר.")
            if resp.status_code >= 500:  # כולל 529 (עומס)
                raise ExtractionError("busy", "שירות המודל עמוס כרגע.")
            raise ExtractionError("api", f"שגיאה בשירות המודל (קוד {resp.status_code}).")

        try:
            data = resp.json()
            text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
            return ModelOutput.model_validate_json(_strip_fence(text))
        except (ValidationError, ValueError, KeyError, TypeError):
            log.warning("anthropic returned invalid json")
            raise ExtractionError("bad_json", "המודל החזיר תשובה לא תקינה לעמוד הזה.") from None


def _strip_fence(text: str) -> str:
    """מסירה עטיפת ```json שמודלים מוסיפים לפעמים סביב התשובה."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return text


# ---------- שרשרת מודלים (החלטה 34) ----------

MIDDLE_TIMEOUT = 45  # מודל באמצע השרשרת (3.8 Flash) לא יתקע את הערימה
PERMANENT = {"quota", "api", "config"}  # כשל שלא יעבור בעמוד הבא: מכסה, קרדיט שנגמר, מפתח שגוי
PROVIDERS = {"gemini": GeminiExtractor, "anthropic": AnthropicExtractor}


class ChainExtractor(FieldExtractor):
    """ראשי וגיבויים לפי הסדר: עמוד שנכשל במודל עובר לבא בתור. נבנית מחדש לכל העלאה."""

    def __init__(self, links: list[FieldExtractor]):
        self.links = links
        self.skipped: set[int] = set()

    def read_page(self, image: bytes, mime_type: str) -> ModelOutput:
        """מנסה כל מודל לפי הסדר; השגיאה של האחרון עוברת לניסיון החוזר של הצינור."""
        last = len(self.links) - 1
        for i, link in enumerate(self.links):
            if i in self.skipped:
                continue
            try:
                out = link.read_page(image, mime_type)
                self.model = link.model
                return out
            except ExtractionError as e:
                if i == last:
                    raise
                log.warning("model fallback from link=%d code=%s", i, e.code)
                if i > 0 or e.code in PERMANENT:
                    self.skipped.add(i)
        raise AssertionError("unreachable")  # המודל האחרון לעולם לא מדולג


def build_extractor() -> FieldExtractor:
    """בונה את המחלץ מ-MODEL_CHAIN ב-.env ("ספק:מודל" מופרדים בפסיק); בלעדיו: GEMINI_MODEL בלבד."""
    spec = os.getenv("MODEL_CHAIN") or f"gemini:{os.getenv('GEMINI_MODEL') or ''}"
    items = [s.strip() for s in spec.split(",") if s.strip()]
    links: list[FieldExtractor] = []
    for i, item in enumerate(items):
        provider, _, model = item.partition(":")
        make = PROVIDERS.get(provider.strip())
        if not make or not model.strip():
            raise ExtractionError("config", "MODEL_CHAIN לא תקין בהגדרות השרת")
        timeout = MIDDLE_TIMEOUT if 0 < i < len(items) - 1 else TIMEOUT_SECONDS
        try:
            links.append(make(model.strip(), timeout=timeout))
        except ExtractionError as e:  # מודל בלי מפתח לא עוצר את השאר
            log.warning("model link=%d skipped (%s)", i, e.code)
    if not links:
        raise ExtractionError("config", "אין אף מודל זמין בהגדרות השרת")
    return links[0] if len(links) == 1 else ChainExtractor(links)
