"""בדיקה ידנית של הצינור דרך השרת הרץ. שימוש:
    python eval/try_upload.py "samples/קובץ.pdf" [קובץ נוסף ...] [--key מפתח] [--json]
Ctrl+C מפסיק את העיבוד בשרת.
"""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import httpx
import pymupdf

SERVER = "http://127.0.0.1:8765"


def slice_pdf(data: bytes, spec: str) -> bytes:
    """מחזירה PDF חדש בזיכרון רק עם העמודים שנבחרו ('1-11')."""
    first, _, last = spec.partition("-")
    with pymupdf.open(stream=data, filetype="pdf") as src, pymupdf.open() as out:
        out.insert_pdf(src, from_page=int(first) - 1, to_page=int(last or first) - 1)
        return out.tobytes()


def describe(r: dict) -> str:
    """שורה קצרה לעמוד: הצליח עם כמה שדות לבדיקה, או נכשל עם קוד."""
    where = f"קובץ {r['file_index']} עמוד {r['page']}"
    if not r["ok"]:
        return f"  {where}: נכשל [{r['error_code']}] {r['error_message']}"
    form = r["form"]
    fields = [v for v in form.values() if isinstance(v, dict) and "status" in v]
    fields += [n for k in ("central_numbers", "commitment_numbers") for n in form[k]]
    review = sum(f["status"] == "review" for f in fields)
    missing = sum(f["status"] == "not_found" for f in fields)
    return f"  {where}: עובד | לבדיקה: {review} | לא נמצא: {missing}"


def main() -> None:
    """מעלה קבצים לשרת, מציגה התקדמות חיה ומדפיסה סיכום."""
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("files", nargs="+")
    p.add_argument("--key", default=None, help="מפתח אידמפוטנטיות (אותו מפתח = אותה עבודה)")
    p.add_argument("--json", action="store_true", help="להדפיס את הרשומות המלאות בסוף")
    p.add_argument("--pages", default=None, help="עמודים מה-PDF הראשון בלבד, למשל 1-11")
    args = p.parse_args()

    files = [("files", (Path(f).name, Path(f).read_bytes())) for f in args.files]
    if args.pages:
        files[0] = ("files", (files[0][1][0], slice_pdf(files[0][1][1], args.pages)))
    key = args.key or uuid.uuid4().hex
    with httpx.Client(base_url=SERVER, timeout=120) as client:
        r = client.post("/api/uploads", files=files, headers={"Idempotency-Key": key})
        if r.status_code != 202:
            print(f"נדחה ({r.status_code}): {r.json().get('detail')}")
            return
        job = r.json()
        print(f"עבודה {job['id']} | עמודים: {job['total_pages']} | מפתח: {key}")
        shown = 0
        try:
            while True:
                for res in job["results"][shown:]:
                    print(describe(res))
                shown = len(job["results"])
                if job["state"] != "running":
                    break
                time.sleep(2)
                job = client.get(f"/api/uploads/{job['id']}").json()
        except KeyboardInterrupt:
            print("מפסיקה...")
            job = client.post(f"/api/uploads/{job['id']}/cancel").json()
            while job["state"] == "running":
                time.sleep(1)
                job = client.get(f"/api/uploads/{job['id']}").json()
            for res in job["results"][shown:]:
                print(describe(res))

    print(f"\n{job['message']} | {job['elapsed_seconds']} שניות")
    if args.json:
        print(json.dumps(job["results"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
