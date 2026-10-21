import { Check, ChevronLeft, ChevronRight, CircleX, LocateFixed, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState, type MouseEvent } from "react";
import type { Commitment } from "../../../api/types";
import type { RecordActions } from "../../../hooks/useCommitments";
import { COLUMNS } from "../../../lib/fields";
import { boxOf, firstFlagged, type FocusKey } from "../../../lib/focus";
import EditableCell from "../../records/EditableCell/EditableCell";
import NumberList from "../../records/NumberList/NumberList";
import StatusBadge from "../../records/StatusBadge/StatusBadge";
import PagePreview from "../PagePreview/PagePreview";
import "./DetailPanel.css";

interface Props {
  record: Commitment;
  file: File | null;
  actions: RecordActions;
  sendersListId: string;
  onPrev: (() => void) | null;
  onNext: (() => void) | null;
  onClose: () => void;
}

/** לוח צד: תמונת הטופס המקורי ליד השדות, לבדיקה ותיקון בעין. Esc סוגר, חצים מדפדפים. */
export default function DetailPanel({ record: r, file, actions, sendersListId, onPrev, onNext, onClose }: Props) {
  const [approving, setApproving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const panel = useRef<HTMLElement>(null);
  const readOnly = r.kind === "sample" || r.state === "failed";

  // השדה שמסומן בתמונת הטופס. כשהלוח נפתח: השדה הכתום הראשון שידוע איפה הוא כתוב
  const [focus, setFocus] = useState<FocusKey | null>(null);

  // המקלדת עוברת ללוח כשהוא נפתח, כדי ש-Esc והחצים יעבדו גם אם הסמן היה בתיבת החיפוש
  useEffect(() => panel.current?.focus(), []);
  useEffect(() => setConfirming(false), [r.id]);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- רק במעבר לרשומה אחרת, לא אחרי כל תיקון
  useEffect(() => setFocus(firstFlagged(r, COLUMNS.map((c) => c.key))), [r.id]);

  /** לחיצה על שדה או על מספר מסמנת אותו בתמונה (העריכה עצמה ממשיכה כרגיל). */
  function select(key: FocusKey | "central" | "commitment", e: MouseEvent) {
    if (key === "central" || key === "commitment") {
      const chip = (e.target as HTMLElement).closest<HTMLElement>("[data-number-id]");
      const list = key === "central" ? r.central_numbers : r.commitment_numbers;
      const id = chip ? Number(chip.dataset.numberId) : list.find((n) => n.box)?.id;
      if (id !== undefined) setFocus(`n${id}`);
      return;
    }
    setFocus(key);
  }

  const numbersOf = (key: string) =>
    key === "central" ? r.central_numbers : key === "commitment" ? r.commitment_numbers : [];
  const isFocused = (key: string) => focus === key || numbersOf(key).some((n) => `n${n.id}` === focus);
  const located = (key: string) =>
    key === "central" || key === "commitment"
      ? numbersOf(key).some((n) => n.box)
      : !!boxOf(r, key as FocusKey);
  const focusBox = boxOf(r, focus);
  const canLocate = file !== null && COLUMNS.some((c) => located(c.key));

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.target as HTMLElement).tagName === "INPUT") return;
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight" && onPrev) onPrev();
      if (e.key === "ArrowLeft" && onNext) onNext();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, onPrev, onNext]);

  async function approve() {
    setApproving(true);
    await actions.approve(r.id);
    setApproving(false);
    onNext?.();
  }

  // אחרי מחיקה עוברים לרשומה הבאה, או הקודמת, או סוגרים
  async function remove() {
    const go = onNext ?? onPrev ?? onClose;
    if (await actions.remove(r.id)) go();
    setConfirming(false);
  }

  const title = r.source_page ? `עמוד ${r.source_page}` : "רשומה";
  const subtitle = r.source_file && r.source_file > 1 ? `קובץ ${r.source_file}` : null;

  return (
    <div className="detail-backdrop" onClick={onClose}>
      <aside
        ref={panel}
        tabIndex={-1}
        className="detail"
        role="dialog"
        aria-modal="true"
        aria-label="פרטי הרשומה"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="detail-head">
          <div className="detail-title">
            <h2>{title}</h2>
            {subtitle && <span className="detail-subtitle">{subtitle}</span>}
            <StatusBadge state={r.state} />
          </div>
          <div className="detail-nav">
            <button className="btn btn-ghost" onClick={onPrev ?? undefined} disabled={!onPrev} aria-label="הקודם">
              <ChevronRight className="icon-sm" />
            </button>
            <button className="btn btn-ghost" onClick={onNext ?? undefined} disabled={!onNext} aria-label="הבא">
              <ChevronLeft className="icon-sm" />
            </button>
            <button className="btn btn-ghost" onClick={onClose} aria-label="סגירה">
              <X className="icon-sm" />
            </button>
          </div>
        </header>

        <div className="detail-body">
          <div className="detail-fields">
            {canLocate && r.state !== "failed" && (
              <p className="detail-locate-hint">
                <LocateFixed className="icon-sm" />
                לחיצה על שדה מסמנת בטופס איפה הוא כתוב
              </p>
            )}
            {r.state === "failed" ? (
              <p className="detail-failed">
                <CircleX className="icon-sm" />
                העמוד לא עובד: {r.error_message}
              </p>
            ) : (
              COLUMNS.map((col) => (
                <div
                  key={col.key}
                  className={canLocate && isFocused(col.key) ? "detail-field detail-field-focus" : "detail-field"}
                  onClickCapture={(e) => select(col.key, e)}
                >
                  <span className="detail-label">
                    {col.label}
                    {canLocate && located(col.key) && (
                      <LocateFixed className="detail-locate" aria-label="מסומן בתמונת הטופס" />
                    )}
                  </span>
                  {col.kind === "field" ? (
                    <EditableCell
                      as="div"
                      field={r[col.key]}
                      readOnly={readOnly}
                      placeholder={col.placeholder}
                      listId={col.key === "sender" ? sendersListId : undefined}
                      onSave={(v) => actions.correctField(r.id, col.key, v)}
                      onConfirm={() => actions.confirmField(r.id, col.key)}
                    />
                  ) : (
                    <NumberList
                      as="div"
                      numbers={col.key === "central" ? r.central_numbers : r.commitment_numbers}
                      readOnly={readOnly}
                      max={col.max}
                      onConfirm={(id) => actions.confirmNumber(r.id, id)}
                      onCorrect={(id, v) => actions.correctNumber(r.id, id, v)}
                      onAdd={(v) => actions.addNumber(r.id, col.key, v)}
                      onDelete={(id) => actions.deleteNumber(r.id, id)}
                    />
                  )}
                </div>
              ))
            )}
          </div>

          <div className="detail-preview">
            <PagePreview file={file} page={r.source_page} sample={r.kind === "sample"} focus={focusBox} />
          </div>
        </div>

        {r.kind !== "sample" && (
          <footer className="detail-foot">
            {confirming ? (
              <div className="detail-confirm">
                <span>למחוק את הרשומה? אי אפשר לבטל.</span>
                <button className="btn btn-danger" onClick={remove}>
                  כן, למחוק
                </button>
                <button className="btn btn-ghost" onClick={() => setConfirming(false)}>
                  ביטול
                </button>
              </div>
            ) : (
              <button className="btn btn-ghost detail-delete" onClick={() => setConfirming(true)}>
                <Trash2 className="icon-sm" />
                מחיקת הרשומה
              </button>
            )}
            {r.state === "pending" && (
              <div className="detail-approve">
                <span className="detail-foot-hint">אחרי אישור עוברים לרשומה הבאה</span>
                <button className="btn btn-primary" onClick={approve} disabled={approving}>
                  <Check className="icon-sm" />
                  אישור הרשומה
                </button>
              </div>
            )}
          </footer>
        )}
      </aside>
    </div>
  );
}
