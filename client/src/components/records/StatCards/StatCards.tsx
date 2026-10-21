import { CircleAlert, CircleCheck, CircleX, Files } from "lucide-react";
import type { CommitmentList } from "../../../api/types";
import type { CardKey } from "../../../lib/filters";
import "./StatCards.css";

interface Props extends Pick<CommitmentList, "counts" | "pending_review"> {
  active: CardKey | null;
  onSelect: (key: CardKey) => void;
}

/** כרטיסי סיכום מעל הטבלה; לחיצה על כרטיס מסננת את הטבלה לפיו. */
export default function StatCards({ counts, pending_review, active, onSelect }: Props) {
  const cards: { key: CardKey; label: string; value: number; Icon: typeof Files }[] = [
    { key: "total", label: "רשומות במערכת", value: counts.pending + counts.approved + counts.failed, Icon: Files },
    { key: "approved", label: "אושרו", value: counts.approved, Icon: CircleCheck },
    { key: "review", label: "ממתינות עם שדות לבדיקה", value: pending_review, Icon: CircleAlert },
    { key: "failed", label: "עמודים שלא עובדו", value: counts.failed, Icon: CircleX },
  ];
  return (
    <section className="stats" aria-label="סיכום">
      {cards.map(({ key, label, value, Icon }) => (
        <button
          key={key}
          className={`card stat stat-${key} ${active === key ? "stat-active" : ""}`}
          aria-pressed={active === key}
          onClick={() => onSelect(key)}
        >
          <div className="stat-icon">
            <Icon />
          </div>
          <div>
            <div className="stat-value">{value}</div>
            <div className="stat-label">{label}</div>
          </div>
        </button>
      ))}
    </section>
  );
}
