import { useEffect, useState } from "react";
import { isPdf, renderPdfPage } from "../lib/pdfPage";

export interface PageImage {
  url: string | null;
  loading: boolean;
  failed: boolean;
}

/** כתובת מקומית לתמונת העמוד של הרשומה: מ-PDF רק העמוד הזה, ותמונה כמו שהיא. משתחררת כשלא צריך. */
export function usePageImage(file: File | null, page: number | null): PageImage {
  const [state, setState] = useState<PageImage>({ url: null, loading: false, failed: false });

  useEffect(() => {
    if (!file) {
      setState({ url: null, loading: false, failed: false });
      return;
    }
    let cancelled = false;
    let url: string | null = null;
    setState({ url: null, loading: true, failed: false });

    const blob = isPdf(file) ? renderPdfPage(file, page ?? 1) : Promise.resolve(file);
    blob.then(
      (b) => {
        if (cancelled) return;
        url = URL.createObjectURL(b);
        setState({ url, loading: false, failed: false });
      },
      () => !cancelled && setState({ url: null, loading: false, failed: true }),
    );

    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [file, page]);

  return state;
}
