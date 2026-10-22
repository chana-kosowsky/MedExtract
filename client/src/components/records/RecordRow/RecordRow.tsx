import { Check, CircleX, Eye, FileQuestion } from "lucide-react";
import { useState } from "react";
import type { Commitment } from "../../../api/types";
import type { RecordActions } from "../../../hooks/useCommitments";
import { COLUMNS, nothingExtracted } from "../../../lib/fields";
import EditableCell from "../EditableCell/EditableCell";
import NumberList from "../NumberList/NumberList";
import StatusBadge from "../StatusBadge/StatusBadge";
import "./RecordRow.css";

interface Props {
  record: Commitment;
  actions: RecordActions;
  sendersListId: string;
  shortNames: Record<string, string>;
  onOpen: () => void;
}

/** מאיפה הגיעה הרשומה: קובץ ועמוד בהעלאה. */
function sourceLabel(r: Commitment): string | null {
  if (r.kind === "sample") return "דוגמה";
  if (r.source_page == null) return null;
  return r.source_file && r.source_file > 1 ? `קובץ ${r.source_file} · עמוד ${r.source_page}` : `עמוד ${r.source_page}`;
}

/** שורה אחת בטבלה: מצב, שבעת השדות לעריכה, וכפתור אישור. עמוד שנכשל, או שלא חולץ ממנו כלום, מוצג בהודעה אחת. */
export default function RecordRow({ record: r, actions, sendersListId, shortNames, onOpen }: Props) {
  const [approving, setApproving] = useState(false);
  const readOnly = r.kind === "sample" || r.state === "failed";
  const source = sourceLabel(r);

  async function approve() {
    setApproving(true);
    await actions.approve(r.id);
    setApproving(false);
  }

  return (
    <tr className={`row row-${r.state}`}>
      <td className="row-status" onClick={onOpen} title="הצגת הטופס">
        <StatusBadge state={r.state} />
        {source && <span className="row-source">{source}</span>}
      </td>

      {r.state === "failed" ? (
        <td className="row-failed-message" colSpan={COLUMNS.length}>
          <CircleX className="icon-sm" />
          העמוד לא עובד: {r.error_message}
        </td>
      ) : nothingExtracted(r) ? (
        <td className="row-empty-message" colSpan={COLUMNS.length} onClick={onOpen}>
          <FileQuestion className="icon-sm" />
          לא חולצו שדות מהעמוד. אפשר לפתוח את הטופס ולהקליד אותם.
        </td>
      ) : (
        COLUMNS.map((col) =>
          col.kind === "field" ? (
            <EditableCell
              key={col.key}
              field={r[col.key]}
              display={col.key === "sender" && r.sender.value ? shortNames[r.sender.value] : undefined}
              readOnly={readOnly}
              placeholder={col.placeholder}
              listId={col.key === "sender" ? sendersListId : undefined}
              onSave={(v) => actions.correctField(r.id, col.key, v)}
              onConfirm={() => actions.confirmField(r.id, col.key)}
            />
          ) : (
            <NumberList
              key={col.key}
              numbers={col.key === "central" ? r.central_numbers : r.commitment_numbers}
              readOnly={readOnly}
              max={col.max}
              onConfirm={(id) => actions.confirmNumber(r.id, id)}
              onCorrect={(id, v) => actions.correctNumber(r.id, id, v)}
              onAdd={(v) => actions.addNumber(r.id, col.key, v)}
              onDelete={(id) => actions.deleteNumber(r.id, id)}
            />
          ),
        )
      )}

      <td className="row-action">
        <div className="row-buttons">
          <button className="btn btn-ghost row-open" onClick={onOpen} aria-label="הצגת הטופס" title="הצגת הטופס">
            <Eye className="icon-sm" />
          </button>
          {r.state === "pending" && r.kind !== "sample" && (
            <button className="btn row-approve" onClick={approve} disabled={approving}>
              <Check className="icon-sm" />
              אישור
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}
