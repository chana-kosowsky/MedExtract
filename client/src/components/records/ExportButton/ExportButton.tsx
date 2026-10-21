import { FileSpreadsheet, LoaderCircle } from "lucide-react";
import { useState } from "react";
import { ApiError, commitments } from "../../../api/client";
import type { ListParams } from "../../../api/types";
import type { Notify } from "../../../hooks/useToast";
import "./ExportButton.css";

interface Props {
  filters: ListParams;
  disabled: boolean;
  notify: Notify;
  onError: (message: string) => void;
}

/** הורדת הרשומות שמוצגות (לפי החיפוש והסינון) כקובץ אקסל. */
export default function ExportButton({ filters, disabled, notify, onError }: Props) {
  const [busy, setBusy] = useState(false);

  async function download() {
    setBusy(true);
    try {
      const { blob, name } = await commitments.exportXlsx(filters);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      notify("קובץ האקסל הורד");
    } catch (e) {
      onError(e instanceof ApiError ? e.message : "הייצוא נכשל. אפשר לנסות שוב.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <button className="btn btn-secondary export" onClick={download} disabled={disabled || busy}>
      {busy ? <LoaderCircle className="icon-sm spin" /> : <FileSpreadsheet className="icon-sm" />}
      ייצוא לאקסל
    </button>
  );
}
