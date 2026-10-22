import { LogOut, ScanText, TriangleAlert } from "lucide-react";
import "./Header.css";

interface Props {
  dbOk: boolean;
  onLogout: (() => void) | null; // null כשהכניסה כבויה בשרת
}

/** כותרת המוצר, מצב המערכת, יציאה, ופס האזהרה של הדמו. */
export default function Header({ dbOk, onLogout }: Props) {
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
          <div className="header-end">
            <div className={dbOk ? "system-status" : "system-status system-status-down"}>
              <span className="system-status-dot" />
              {dbOk ? "המערכת פעילה" : "אין חיבור למסד הנתונים"}
            </div>
            {onLogout && (
              <button className="btn btn-ghost header-logout" onClick={onLogout}>
                <LogOut className="icon-sm" />
                יציאה
              </button>
            )}
          </div>
        </div>
      </div>
      <div className="demo-banner">
        <TriangleAlert className="icon-sm" />
        <span>
          <strong>סביבת הדגמה.</strong> אין להעלות מסמכים רפואיים אמיתיים: הרשומות גלויות לכל מי שנכנס עם משתמש הדמו.
        </span>
      </div>
    </header>
  );
}
