import type { TranslationJobStatus } from "@/types/job";


export interface JobStatusPresentation {
  label: string;
  detail: string;
  tone: "neutral" | "active" | "ready" | "danger";
}


const presentations: Record<TranslationJobStatus, JobStatusPresentation> = {
  QUEUED: {
    label: "Menunggu",
    detail: "Pekerjaan menunggu worker yang tersedia.",
    tone: "neutral",
  },
  PROCESSING: {
    label: "Menyiapkan halaman",
    detail: "Worker sedang merender halaman PDF menjadi preview.",
    tone: "active",
  },
  READY_FOR_TRANSLATION: {
    label: "Siap untuk AI",
    detail: "Seluruh halaman sudah siap untuk tahap OCR dan terjemahan.",
    tone: "ready",
  },
  FAILED: {
    label: "Gagal diproses",
    detail: "Persiapan PDF gagal. Periksa layanan worker lalu coba lagi.",
    tone: "danger",
  },
};


export function getJobStatusPresentation(
  status: TranslationJobStatus,
  failureCode?: string | null,
): JobStatusPresentation {
  if (status === "FAILED" && failureCode === "QUEUE_UNAVAILABLE") {
    return {
      label: "Antrean tidak tersedia",
      detail: "Worker tidak dapat menerima pekerjaan. Nyalakan Redis lalu coba lagi.",
      tone: "danger",
    };
  }
  return presentations[status];
}


export function shouldRefreshJobStatus(status: TranslationJobStatus): boolean {
  return status === "QUEUED" || status === "PROCESSING";
}
