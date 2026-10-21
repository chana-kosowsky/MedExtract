import { Check, CircleAlert, Plus, X } from "lucide-react";
import { useState, type KeyboardEvent } from "react";
import type { NumberValue } from "../../../api/types";
import { reviewTip } from "../../../lib/fields";
import "./NumberList.css";

interface Props {
  numbers: NumberValue[];
  readOnly: boolean;
  max?: number;
  as?: "td" | "div";
  onCorrect: (numberId: number, value: string) => Promise<boolean>;
  onAdd: (value: string) => Promise<boolean>;
  onDelete: (numberId: number) => Promise<boolean>;
  onConfirm?: (numberId: number) => Promise<boolean>;
}

/** שדה קטן לעריכת מספר: Enter שומר, Esc מבטל. */
function NumberInput({ initial, onDone }: { initial: string; onDone: (value: string | null) => void }) {
  const [draft, setDraft] = useState(initial);
  function onKey(e: KeyboardEvent) {
    if (e.key === "Enter") onDone(draft.trim() || null);
    if (e.key === "Escape") onDone(null);
  }
  return (
    <input
      className="number-input"
      autoFocus
      inputMode="numeric"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onKeyDown={onKey}
      onBlur={() => onDone(draft.trim() || null)}
    />
  );
}

/** תא עם רשימת מספרים כתגיות: לחיצה מתקנת, ✓ מאשר מספר כתום, X מוחק, + מוסיף (עד max). רשימה ריקה מסומנת. */
export default function NumberList(props: Props) {
  const { numbers, readOnly, max = Infinity, as: Tag = "td", onCorrect, onAdd, onDelete, onConfirm } = props;
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const flagged = numbers.length === 0 || numbers.some((n) => n.status !== "ok");

  async function finish(id: number | "new", value: string | null) {
    setEditing(null);
    if (value === null) return;
    if (id === "new") await onAdd(value);
    else if (value !== numbers.find((n) => n.id === id)?.value) await onCorrect(id, value);
  }

  return (
    <Tag className={flagged ? "numbers numbers-flagged" : "numbers"}>
      <div className="numbers-list">
        {numbers.length === 0 && editing !== "new" && <span className="numbers-empty">חסר</span>}
        {numbers.map((n) =>
          editing === n.id ? (
            <NumberInput key={n.id} initial={n.value ?? ""} onDone={(v) => finish(n.id, v)} />
          ) : (
            <span
              key={n.id}
              data-number-id={n.id}
              className={n.status === "ok" ? "chip" : "chip chip-review"}
              onClick={() => !readOnly && setEditing(n.id)}
            >
              {n.status !== "ok" && <CircleAlert className="chip-flag" />}
              <span className="chip-value">{n.value}</span>
              {!readOnly && onConfirm && n.status === "review" && n.value && (
                <button
                  className="chip-confirm"
                  aria-label="המספר נכון"
                  title="המספר נכון"
                  onClick={(e) => {
                    e.stopPropagation();
                    onConfirm(n.id);
                  }}
                >
                  <Check />
                </button>
              )}
              {!readOnly && (
                <button
                  className="chip-delete"
                  aria-label="מחיקת מספר"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(n.id);
                  }}
                >
                  <X />
                </button>
              )}
              {reviewTip(n) && <span className="chip-tip">{reviewTip(n)}</span>}
            </span>
          ),
        )}
        {editing === "new" && <NumberInput initial="" onDone={(v) => finish("new", v)} />}
        {!readOnly && editing === null && numbers.length < max && (
          <button className="numbers-add" aria-label="הוספת מספר" onClick={() => setEditing("new")}>
            <Plus />
          </button>
        )}
      </div>
    </Tag>
  );
}
