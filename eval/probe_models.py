"""בדיקה חד-פעמית: אילו מודלים זמינים במפתח הנוכחי, וכמה זמן לוקח עמוד אחד. שימוש:
    python eval/probe_models.py "samples/קובץ.pdf" 1 gemini-4-argon gemini-3.8-flash ...
בקשה אחת לכל מודל. לא מדפיס תוכן מהטופס מעבר לשדות שנבדקים.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import pymupdf
import truststore

from app.extractor import ExtractionError, GeminiExtractor
from app.pipeline import render_pdf_page


def main() -> None:
    """שולחת עמוד אחד לכל מודל ומדפיסה זמינות, זמן ומה נקרא."""
    sys.stdout.reconfigure(encoding="utf-8")
    truststore.inject_into_ssl()
    pdf, page, models = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
    with pymupdf.open(pdf) as doc:
        image, mime = render_pdf_page(doc, page - 1)
    for model in models:
        t0 = time.perf_counter()
        try:
            raw = GeminiExtractor(model).read_page(image, mime)
        except ExtractionError as e:
            print(f"{model}: נכשל [{e.code}] {e.message}")
            continue
        sec = time.perf_counter() - t0
        central = [(n.text, n.label) for n in raw.central_numbers]
        commit = [(n.text, n.label) for n in raw.commitment_numbers]
        print(f"{model}: {sec:.1f}s | שם: {raw.first_name.text} {raw.last_name.text} | ת\"ז: {raw.id_number.text} | "
              f"מרכזי: {central} | התחייבות: {commit} | חותמת: {raw.received_date_stamp.text} | "
              f"כתב יד: {raw.received_date_handwritten.text} | גורם: {raw.sender.text}")


if __name__ == "__main__":
    main()
