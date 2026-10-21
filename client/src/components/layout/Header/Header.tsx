import { ScanText, TriangleAlert } from "lucide-react";
import "./Header.css";

/** כותרת המוצר ופס האזהרה של הדמו. */
export default function Header({ dbOk }: { dbOk: boolean }) {
  return (
    <header className="header">
      <div className="header-bar">
        <div className="header-inner">
          <div className="brand">
            <div className="brand-logo">
              <ScanText />
            </div>
            <div>
              <h1 className="brand-name">MedExtract</h1>
              <p className="brand-tagline">מטפסי התחייבות לנתונים מובנים, בדקות</p>
            </div>
          </div>
          <div className={dbOk ? "system-status" : "system-status system-status-down"}>
            <span className="system-status-dot" />
            {dbOk ? "המערכת פעילה" : "אין חיבור למסד הנתונים"}
          </div>
        </div>
      </div>
      <div className="demo-banner">
        <TriangleAlert className="icon-sm" />
        <span>
          <strong>סביבת הדגמה.</strong> אין להעלות מסמכים רפואיים אמיתיים: הרשומות גלויות לכל מי שנכנס לקישור.
        </span>
      </div>
    </header>
  );
}
