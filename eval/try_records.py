"""בדיקה ידנית של שלב 5 מול השרת הרץ. שימוש:
    python eval/try_records.py create   (מעבד 2 עמודים, מתקן שם משפחה ומאשר)
    python eval/try_records.py verify   (אחרי הפעלה מחדש של השרת: הרשומה עדיין שם?)
"""
import sys
import time
import uuid
from pathlib import Path

import httpx

from try_upload import SERVER, slice_pdf

ROOT = Path(__file__).resolve().parents[1]
NEW_LAST_NAME = "כהן-בדיקה"


def create(client: httpx.Client) -> None:
    """מעלה את עמודים 1–2 מקובץ הדוגמה, מתקנת את הרשומה הראשונה ומאשרת אותה."""
    pdf = max((ROOT / "samples").glob("*.pdf"), key=lambda p: p.stat().st_size)
    files = [("files", ("sample.pdf", slice_pdf(pdf.read_bytes(), "1-2")))]
    job = client.post("/api/uploads", files=files, headers={"Idempotency-Key": uuid.uuid4().hex}).json()
    print(f"מעבד {job['total_pages']} עמודים...")
    while job["state"] == "running":
        time.sleep(2)
        job = client.get(f"/api/uploads/{job['id']}").json()
    print(job["message"])

    rid = next(r["record_id"] for r in job["results"] if r["ok"] and r["record_id"])
    before = client.get(f"/api/commitments/{rid}").json()
    print(f"\nרשומה: {rid}")
    print(f"  שם משפחה לפני: {before['last_name']['value']} ({before['last_name']['status']})")
    after = client.patch(f"/api/commitments/{rid}/fields/last_name", json={"value": NEW_LAST_NAME}).json()
    print(f"  שם משפחה אחרי תיקון: {after['last_name']['value']} ({after['last_name']['status']})")
    approved = client.post(f"/api/commitments/{rid}/approve").json()
    print(f"  סטטוס אחרי אישור: {approved['state']}")
    print("\nעכשיו: הפעילי מחדש את השרת, ואז הריצי: try_records.py verify")


def verify(client: httpx.Client) -> None:
    """מוצאת את הרשומה שאושרה אחרונה ומראה שהיא נשמרה."""
    items = client.get("/api/commitments", params={"state": "approved", "limit": 1}).json()["items"]
    if not items:
        print("לא נמצאה רשומה מאושרת. ✗")
        return
    r = items[0]
    ok = r["state"] == "approved" and r["last_name"]["value"] == NEW_LAST_NAME
    print(f"רשומה: {r['id']}")
    print(f"  סטטוס: {r['state']} | אושרה: {r['approved_at']}")
    print(f"  שם משפחה: {r['last_name']['value']} ({r['last_name']['status']})")
    print(f"  מספרים מרכזיים: {[n['value'] for n in r['central_numbers']]}")
    print("\nהרשומה נשמרה וחזרה אחרי הפעלה מחדש. ✓" if ok else "\nמשהו לא תואם. ✗")


def main() -> None:
    """מריצה create או verify."""
    sys.stdout.reconfigure(encoding="utf-8")
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    with httpx.Client(base_url=SERVER, timeout=120) as client:
        if action == "create":
            create(client)
        elif action == "verify":
            verify(client)
        else:
            print(__doc__)


if __name__ == "__main__":
    main()
