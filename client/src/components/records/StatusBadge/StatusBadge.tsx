import { CircleCheck, CircleX, Clock } from "lucide-react";
import type { RecordState } from "../../../api/types";
import "./StatusBadge.css";

const LABELS: Record<RecordState, string> = { pending: "ממתין", approved: "אושר", failed: "נכשל" };
const ICONS = { pending: Clock, approved: CircleCheck, failed: CircleX };

/** תגית מצב הרשומה: ממתין / אושר / נכשל. */
export default function StatusBadge({ state }: { state: RecordState }) {
  const Icon = ICONS[state];
  return (
    <span className={`badge badge-${state}`}>
      <Icon />
      {LABELS[state]}
    </span>
  );
}
