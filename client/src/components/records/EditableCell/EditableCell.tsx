import { Check, CircleAlert, LoaderCircle, Pencil } from "lucide-react";
import { useState, type KeyboardEvent, type MouseEvent } from "react";
import type { FieldValue } from "../../../api/types";
import { reviewTip } from "../../../lib/fields";
import "./EditableCell.css";

interface Props {
  field: FieldValue;
  display?: string; // טקסט קצר להצגה במקום הערך (השם המלא נשמר ומופיע בריחוף ובעריכה)
  readOnly: boolean;
  placeholder?: string;
  listId?: string;
  as?: "td" | "div";
  onSave: (value: string) => Promise<boolean>;
  onConfirm?: () => Promise<boolean>;
}

/** תא בטבלה: מציג ערך (כתום אם לא בטוח), ובלחיצה הופך לשדה עריכה. Enter שומר, Esc מבטל, ✓ מאשר כמו שהוא. */
export default function EditableCell(props: Props) {
  const { field, display, readOnly, placeholder, listId, as: Tag = "td", onSave, onConfirm } = props;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const tip = reviewTip(field);

  function open() {
    if (readOnly || saving) return;
    setDraft(field.value ?? "");
    setEditing(true);
  }

  async function commit() {
    setEditing(false);
    if (draft.trim() === (field.value ?? "")) return;
    setSaving(true);
    await onSave(draft.trim());
    setSaving(false);
  }

  // ✓ על שדה כתום: הבודקת אישרה שהערך נכון, בלי לערוך
  const canConfirm = !!onConfirm && field.status === "review" && !!field.value;
  async function confirm(e: MouseEvent) {
    e.stopPropagation();
    setSaving(true);
    await onConfirm?.();
    setSaving(false);
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === "Enter") commit();
    if (e.key === "Escape") setEditing(false);
  }

  const tone = field.status === "review" ? "cell-review" : field.status === "not_found" ? "cell-missing" : "cell-ok";

  return (
    <Tag className={`cell ${tone} ${readOnly ? "" : "cell-editable"}`} onClick={open}>
      {editing ? (
        <input
          className="cell-input"
          autoFocus
          value={draft}
          placeholder={placeholder}
          list={listId}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKey}
          onBlur={commit}
        />
      ) : (
        <div className="cell-content">
          {field.status === "review" && <CircleAlert className="cell-flag" />}
          <span
            className={field.value ? "cell-value" : "cell-empty"}
            title={display && display !== field.value ? (field.value ?? undefined) : undefined}
          >
            {field.value ? display || field.value : "חסר"}
          </span>
          <span className="cell-actions">
            {saving ? (
              <LoaderCircle className="cell-spinner" />
            ) : (
              !readOnly && (
                <>
                  {canConfirm && (
                    <button className="cell-confirm" onClick={confirm} aria-label="הערך נכון" title="הערך נכון">
                      <Check />
                    </button>
                  )}
                  <Pencil className="cell-pencil" />
                </>
              )
            )}
          </span>
        </div>
      )}
      {tip && !editing && <span className="cell-tip">{tip}</span>}
    </Tag>
  );
}
