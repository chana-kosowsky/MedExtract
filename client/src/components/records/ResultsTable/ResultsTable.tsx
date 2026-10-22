import { CheckCheck, ChevronDown, LoaderCircle, SearchX, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { Commitment } from "../../../api/types";
import { PAGE_SIZE, type RecordActions } from "../../../hooks/useCommitments";
import { COLUMNS } from "../../../lib/fields";
import RecordRow from "../RecordRow/RecordRow";
import "./ResultsTable.css";

interface Props {
  items: Commitment[];
  total: number;
  loading: boolean;
  error: string | null;
  senders: string[];
  shortNames: Record<string, string>;
  actions: RecordActions;
  toolbar: ReactNode;
  exportButton: ReactNode;
  filtered: boolean;
  onOpen: (id: string) => void;
  onClearError: () => void;
  onShowMore: () => void;
}

/** מזהה רשימת ההשלמה של הגורמים השולחים (משותפת לטבלה וללוח הצד). */
export const SENDERS_LIST_ID = "senders-list";

const STEPS = [
  { title: "מעלים", text: "גוררים PDF סרוק או צילומים מהטלפון. כל עמוד הוא התחייבות." },
  { title: "בודקים את הכתום", text: "שדה שהמערכת לא בטוחה בו נצבע כתום. לוחצים עליו ומתקנים." },
  { title: "מאשרים", text: "אישור שומר את הרשומה. אפשר לחפש, לסנן ולייצא לאקסל." },
];

/** מה מוצג כשאין רשומות: טעינה, אין תוצאות לסינון, או הסבר בשלושה צעדים למבקר חדש. */
function EmptyState({ loading, filtered }: { loading: boolean; filtered: boolean }) {
  if (loading || filtered) {
    return (
      <div className="records-empty">
        {loading ? <LoaderCircle className="records-empty-icon spin" /> : <SearchX className="records-empty-icon" />}
        <p>{loading ? "טעינת רשומות…" : "לא נמצאו רשומות שמתאימות לחיפוש ולסינון."}</p>
      </div>
    );
  }
  return (
    <div className="records-onboarding">
      <p className="records-onboarding-title">עדיין אין רשומות. ככה זה עובד:</p>
      <ol className="records-steps">
        {STEPS.map((s, i) => (
          <li key={s.title} className="records-step">
            <span className="records-step-number">{i + 1}</span>
            <div>
              <p className="records-step-title">{s.title}</p>
              <p className="records-step-text">{s.text}</p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** טבלת הרשומות: שורה לכל התחייבות, עמודה לכל שדה, ואישור של כל הרשומות הבטוחות. */
export default function ResultsTable(props: Props) {
  const { items, total, loading, error, senders, shortNames, actions, toolbar, exportButton, filtered } = props;
  const { onOpen, onClearError, onShowMore } = props;
  const [approving, setApproving] = useState(false);
  const safe = items.filter((r) => r.state === "pending" && !r.needs_review && r.kind === "user").length;

  async function approveSafe() {
    setApproving(true);
    await actions.approveSafe();
    setApproving(false);
  }

  return (
    <section className="card records">
      <header className="records-head">
        <div>
          <h2 className="records-title">רשומות</h2>
          <p className="records-hint">שדה כתום דורש בדיקה. לחיצה על שדה פותחת אותו לתיקון, ועל העין מציגה את הטופס.</p>
        </div>
        <div className="records-actions">
          {exportButton}
          <button className="btn btn-primary" onClick={approveSafe} disabled={safe === 0 || approving}>
            {approving ? <LoaderCircle className="icon-sm spin" /> : <CheckCheck className="icon-sm" />}
            אישור כל הבטוחות ({safe})
          </button>
        </div>
      </header>

      {toolbar}

      {error && (
        <div className="records-alert">
          <span>{error}</span>
          <button aria-label="סגירה" onClick={onClearError}>
            <X className="icon-sm" />
          </button>
        </div>
      )}

      <datalist id={SENDERS_LIST_ID}>
        {senders.map((s) => (
          <option key={s} value={s} />
        ))}
      </datalist>

      {items.length === 0 ? (
        <EmptyState loading={loading} filtered={filtered} />
      ) : (
        <div className="records-scroll">
          <table className="records-table">
            <thead>
              <tr>
                <th>מצב</th>
                {COLUMNS.map((c) => (
                  <th key={c.key}>{c.label}</th>
                ))}
                <th aria-label="פעולות" />
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <RecordRow
                  key={r.id}
                  record={r}
                  actions={actions}
                  sendersListId={SENDERS_LIST_ID}
                  shortNames={shortNames}
                  onOpen={() => onOpen(r.id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {items.length > 0 && (
        <footer className="records-more">
          <span>
            מוצגות {items.length} מתוך {total} רשומות{items.length < total && ", החדשות קודם"}
          </span>
          {items.length < total && (
            <button className="btn btn-secondary" onClick={onShowMore} disabled={loading}>
              {loading ? <LoaderCircle className="icon-sm spin" /> : <ChevronDown className="icon-sm" />}
              הצגת {Math.min(PAGE_SIZE, total - items.length)} ישנות יותר
            </button>
          )}
        </footer>
      )}
    </section>
  );
}
