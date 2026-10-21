import { useCallback, useState } from "react";
import type { ListParams } from "./api/types";
import DetailPanel from "./components/detail/DetailPanel/DetailPanel";
import Header from "./components/layout/Header/Header";
import Toast from "./components/layout/Toast/Toast";
import WakeScreen from "./components/layout/WakeScreen/WakeScreen";
import ExportButton from "./components/records/ExportButton/ExportButton";
import RecordsToolbar from "./components/records/RecordsToolbar/RecordsToolbar";
import ResultsTable, { SENDERS_LIST_ID } from "./components/records/ResultsTable/ResultsTable";
import StatCards from "./components/records/StatCards/StatCards";
import ProgressPanel from "./components/upload/ProgressPanel/ProgressPanel";
import UploadZone from "./components/upload/UploadZone/UploadZone";
import { useCommitments } from "./hooks/useCommitments";
import { useServerWake } from "./hooks/useServerWake";
import { useToast } from "./hooks/useToast";
import { useUploadJob } from "./hooks/useUploadJob";
import { activeCard, CARD_FILTERS, hasFilters, type CardKey } from "./lib/filters";
import "./App.css";

/** המסך הראשי: מחכה לשרת, ואז העלאה, התקדמות, סיכום, סינון וטבלת הרשומות. */
export default function App() {
  const server = useServerWake();
  const { toast, notify, dismiss } = useToast();
  const [filters, setFilters] = useState<ListParams>({});
  const records = useCommitments(filters, notify);
  const upload = useUploadJob(records.refresh);

  const [openId, setOpenId] = useState<string | null>(null);

  const changeFilters = useCallback((patch: Partial<ListParams>) => setFilters((f) => ({ ...f, ...patch })), []);
  const selectCard = useCallback((key: CardKey) => changeFilters(CARD_FILTERS[key]), [changeFilters]);
  const closePanel = useCallback(() => setOpenId(null), []);

  // הרשומה הפתוחה בלוח הצד, והשכנות שלה לדפדוף
  const openIndex = records.items.findIndex((r) => r.id === openId);
  const openRecord = openIndex >= 0 ? records.items[openIndex] : null;
  const neighbor = (step: number) => {
    const next = records.items[openIndex + step];
    return next ? () => setOpenId(next.id) : null;
  };

  if (server.status !== "ready") return <WakeScreen status={server.status} onRetry={server.retry} />;

  return (
    <div className="app">
      <Header dbOk={server.dbOk} />
      <main className="app-main">
        {upload.job ? (
          <ProgressPanel
            job={upload.job}
            elapsed={upload.elapsed}
            canResume={upload.canResume}
            remaining={upload.remaining}
            sending={upload.sending}
            stopping={upload.stopping}
            error={upload.error}
            onCancel={upload.cancel}
            onResume={upload.resume}
            onNew={upload.reset}
          />
        ) : (
          <UploadZone sending={upload.sending} serverError={upload.error} onStart={upload.start} />
        )}

        <StatCards
          counts={records.counts}
          pending_review={records.pending_review}
          active={activeCard(filters)}
          onSelect={selectCard}
        />

        <ResultsTable
          items={records.items}
          total={records.total}
          loading={records.loading}
          onShowMore={records.showMore}
          error={records.error}
          senders={records.senders}
          actions={records.actions}
          filtered={hasFilters(filters)}
          onOpen={setOpenId}
          onClearError={records.clearError}
          exportButton={
            <ExportButton
              filters={filters}
              disabled={records.total === 0}
              notify={notify}
              onError={records.showError}
            />
          }
          toolbar={
            <RecordsToolbar
              filters={filters}
              senders={records.senders}
              currentBatch={upload.job?.batch_id ?? null}
              shown={records.total}
              onChange={changeFilters}
              onClear={() => setFilters({})}
            />
          }
        />
      </main>

      {openRecord && (
        <DetailPanel
          record={openRecord}
          file={upload.fileFor(openRecord.batch_id, openRecord.source_file)}
          actions={records.actions}
          sendersListId={SENDERS_LIST_ID}
          onPrev={neighbor(-1)}
          onNext={neighbor(1)}
          onClose={closePanel}
        />
      )}

      <Toast toast={toast} onDismiss={dismiss} />
    </div>
  );
}
