import type { Commitment, CommitmentList, Job, ListParams, NumberKind, SingleField } from "./types";

/** שגיאה מהשרת, עם הודעה בעברית להצגה וקוד ה-HTTP (0 = אין חיבור). */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status = 0,
  ) {
    super(message);
  }
}

/** הודעה בעברית לשגיאה שהשרת לא הסביר בעצמו. */
function statusMessage(status: number): string {
  if (status === 413) return "ההעלאה גדולה מדי.";
  if (status === 422 || status === 400) return "הבקשה לא תקינה. כדאי לרענן את הדף ולנסות שוב.";
  if (status === 429) return "יותר מדי בקשות. אפשר לנסות שוב בעוד רגע.";
  if (status === 404) return "לא נמצא. ייתכן שהרשומה נמחקה.";
  if (status >= 500) return "השרת לא זמין כרגע. אפשר לנסות שוב בעוד רגע.";
  return `משהו השתבש (${status}). אפשר לנסות שוב.`;
}

const NO_CONNECTION = "אין חיבור לשרת. כדאי לבדוק את החיבור ולנסות שוב.";

/** קריאה לשרת: מחזירה את התשובה, או זורקת ApiError עם הודעה בעברית. */
async function call(path: string, init?: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(NO_CONNECTION);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = body && typeof body.detail === "string" ? body.detail : null;
    throw new ApiError(detail ?? statusMessage(res.status), res.status);
  }
  return res;
}

/** קריאה לשרת שמחזירה JSON. */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await call(path, init);
  return (await res.json().catch(() => null)) as T;
}

/** פרמטרי החיפוש והסינון כמחרוזת שאילתה. */
function query(params: ListParams): URLSearchParams {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && qs.set(k, String(v)));
  return qs;
}

/** בקשה עם גוף JSON. */
function json<T>(path: string, method: string, data?: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
}

/** בדיקה שהשרת ער; מחזירה אם המסד תקין. זורקת אם השרת לא עונה. */
export async function checkHealth(): Promise<boolean> {
  const res = await fetch("/health");
  const body = await res.json().catch(() => ({}));
  return body.db === "ok";
}

/** המשך העלאה שנעצרה: ההעלאה המקורית והעמודים שכבר עובדו. */
export interface ResumeInfo {
  batchId: string;
  skip: { file: number; page: number }[];
}

export const uploads = {
  start(files: File[], key: string, resume?: ResumeInfo) {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    if (resume) {
      form.append("resume_of", resume.batchId);
      form.append("skip", resume.skip.map((s) => `${s.file}:${s.page}`).join(","));
    }
    return request<Job>("/api/uploads", { method: "POST", body: form, headers: { "Idempotency-Key": key } });
  },
  get: (id: string) => request<Job>(`/api/uploads/${id}`),
  cancel: (id: string) => json<Job>(`/api/uploads/${id}/cancel`, "POST"),
};

/** הרשימה הסגורה של הגורמים השולחים: שם מלא, ושם קצר לטבלה. */
export const getSenders = () => request<{ name: string; short: string }[]>("/api/senders");

export const commitments = {
  list: (params: ListParams & { limit?: number } = {}) =>
    request<CommitmentList>(`/api/commitments?${query(params)}`),
  /** קובץ אקסל של הרשומות לפי אותו חיפוש וסינון, עם שם הקובץ מהשרת. */
  async exportXlsx(params: ListParams = {}) {
    const res = await call(`/api/commitments/export?${query(params)}`);
    const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1];
    return { blob: await res.blob(), name: name ?? "medextract.xlsx" };
  },
  get: (id: string) => request<Commitment>(`/api/commitments/${id}`),
  correctField: (id: string, field: SingleField, value: string) =>
    json<Commitment>(`/api/commitments/${id}/fields/${field}`, "PATCH", { value }),
  addNumber: (id: string, kind: NumberKind, value: string) =>
    json<Commitment>(`/api/commitments/${id}/numbers`, "POST", { kind, value }),
  correctNumber: (id: string, numberId: number, value: string) =>
    json<Commitment>(`/api/commitments/${id}/numbers/${numberId}`, "PATCH", { value }),
  deleteNumber: (id: string, numberId: number) =>
    json<Commitment>(`/api/commitments/${id}/numbers/${numberId}`, "DELETE"),
  confirmField: (id: string, field: SingleField) =>
    json<Commitment>(`/api/commitments/${id}/fields/${field}/confirm`, "POST"),
  confirmNumber: (id: string, numberId: number) =>
    json<Commitment>(`/api/commitments/${id}/numbers/${numberId}/confirm`, "POST"),
  approve: (id: string) => json<Commitment>(`/api/commitments/${id}/approve`, "POST"),
  remove: (id: string) => call(`/api/commitments/${id}`, { method: "DELETE" }),
  approveSafe: (batchId?: string) =>
    json<{ approved: number }>(`/api/commitments/approve-safe${batchId ? `?batch_id=${batchId}` : ""}`, "POST"),
};
