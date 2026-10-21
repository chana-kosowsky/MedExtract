"""הרצה ידנית של החילוץ על כמה עמודים מ-PDF. שימוש:
    python eval/try_extract.py "samples/קובץ.pdf" 1 2 3
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import pymupdf as fitz

from app.extractor import ExtractionError, GeminiExtractor

DPI = 200


def render_page(doc: fitz.Document, page_no: int) -> bytes:
    """ממירה עמוד (ממוספר מ-1) לתמונת PNG בזיכרון, בלי קובץ."""
    return doc[page_no - 1].get_pixmap(dpi=DPI).tobytes("png")


def main() -> None:
    """מריצה חילוץ על העמודים שהתבקשו ומדפיסה JSON או הודעת שגיאה לכל עמוד."""
    sys.stdout.reconfigure(encoding="utf-8")
    pdf, pages = sys.argv[1], [int(p) for p in sys.argv[2:]]
    extractor = GeminiExtractor()
    print(f"model: {extractor.model}")
    with fitz.open(pdf) as doc:
        for page_no in pages:
            start = time.perf_counter()
            try:
                form = extractor.extract(render_page(doc, page_no), "image/png", source_page=page_no)
                print(f"\n=== עמוד {page_no} ({time.perf_counter() - start:.1f} שניות) ===")
                print(form.model_dump_json(indent=2, exclude={"form_id"}))
            except ExtractionError as e:
                print(f"\n=== עמוד {page_no}: נכשל [{e.code}] {e.message} ===")


if __name__ == "__main__":
    main()
