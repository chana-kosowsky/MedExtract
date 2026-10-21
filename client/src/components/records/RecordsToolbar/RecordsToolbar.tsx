import { FilterX, Search } from "lucide-react";
import { useEffect, useState } from "react";
import type { ListParams, RecordState } from "../../../api/types";
import { hasFilters } from "../../../lib/filters";
import "./RecordsToolbar.css";

interface Props {
  filters: ListParams;
  senders: string[];
  currentBatch: string | null;
  shown: number;
  onChange: (patch: Partial<ListParams>) => void;
  onClear: () => void;
}

const STATES: { value?: RecordState; label: string }[] = [
  { label: "הכל" },
  { value: "pending", label: "ממתין" },
  { value: "approved", label: "אושר" },
  { value: "failed", label: "נכשל" },
];

const SEARCH_DELAY_MS = 300;

/** מתג קטן (כן / לא) עם תווית. */
function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className={checked ? "toggle toggle-on" : "toggle"}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="toggle-track">
        <span className="toggle-thumb" />
      </span>
      {label}
    </label>
  );
}

/** סרגל חיפוש וסינון מעל הטבלה: טקסט חופשי, גורם שולח, מצב, ורק מה שדורש בדיקה. */
export default function RecordsToolbar({ filters, senders, currentBatch, shown, onChange, onClear }: Props) {
  const [text, setText] = useState(filters.q ?? "");

  // החיפוש נשלח רק כשמפסיקים להקליד לרגע
  useEffect(() => {
    if (text === (filters.q ?? "")) return;
    const timer = setTimeout(() => onChange({ q: text || undefined }), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [text, filters.q, onChange]);

  // ניקוי מבחוץ מנקה גם את תיבת החיפוש
  useEffect(() => {
    if (!filters.q) setText("");
  }, [filters.q]);

  return (
    <div className="toolbar">
      <div className="toolbar-row">
        <div className="toolbar-search">
          <Search className="toolbar-search-icon" />
          <input
            type="search"
            placeholder="חיפוש לפי שם, ת״ז או מספר…"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </div>

        <select
          className="toolbar-select"
          value={filters.sender ?? ""}
          onChange={(e) => onChange({ sender: e.target.value || undefined })}
        >
          <option value="">כל הגורמים השולחים</option>
          {senders.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>

        <div className="segmented" role="radiogroup" aria-label="מצב">
          {STATES.map((s) => (
            <button
              key={s.label}
              role="radio"
              aria-checked={filters.state === s.value}
              className={filters.state === s.value ? "segment segment-active" : "segment"}
              onClick={() => onChange({ state: s.value })}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      <div className="toolbar-row toolbar-row-secondary">
        <Toggle
          label="רק מה שדורש בדיקה"
          checked={!!filters.needs_review}
          onChange={(v) => onChange({ needs_review: v || undefined })}
        />
        {currentBatch && (
          <Toggle
            label="רק ההעלאה הנוכחית"
            checked={filters.batch_id === currentBatch}
            onChange={(v) => onChange({ batch_id: v ? currentBatch : undefined })}
          />
        )}
        <span className="toolbar-count">{shown} רשומות</span>
        {hasFilters(filters) && (
          <button className="btn btn-ghost toolbar-clear" onClick={onClear}>
            <FilterX className="icon-sm" />
            ניקוי סינון
          </button>
        )}
      </div>
    </div>
  );
}
