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
    detail: "Seluruh halaman siap. Mulai terjemahan saat Anda siap memakai kuota AI.",
    tone: "ready",
  },
  TRANSLATION_QUEUED: {
    label: "Menunggu AI",
    detail: "Terjemahan sudah masuk antrean worker.",
    tone: "active",
  },
  TRANSLATING: {
    label: "Menerjemahkan",
    detail: "AI sedang membaca dan menerjemahkan halaman manga.",
    tone: "active",
  },
  COMPLETED: {
    label: "Selesai",
    detail: "PDF terjemahan bahasa Indonesia siap diunduh.",
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
  if (status === "FAILED" && failureCode === "AI_NOT_CONFIGURED") {
    return {
      label: "AI belum dikonfigurasi",
      detail: "Isi GEMINI_API_KEY pada server, lalu coba terjemahkan lagi.",
      tone: "danger",
    };
  }
  if (status === "FAILED" && failureCode === "AI_TRANSLATION_FAILED") {
    return {
      label: "Terjemahan AI gagal",
      detail: "Periksa API key dan kuota Gemini, lalu coba terjemahkan lagi.",
      tone: "danger",
    };
  }
  if (status === "FAILED" && failureCode === "AI_RATE_LIMITED") {
    return {
      label: "Batas Gemini tercapai",
      detail: "Tunggu reset kuota Gemini atau aktifkan billing, lalu coba lagi.",
      tone: "danger",
    };
  }
  if (
    status === "FAILED" &&
    (failureCode === "RESULT_BUILD_FAILED" ||
      failureCode === "TRANSLATION_FAILED")
  ) {
    return {
      label: "Terjemahan gagal",
      detail: "Pemrosesan terhenti. Anda dapat mencoba terjemahan lagi.",
      tone: "danger",
    };
  }
  return presentations[status];
}


export function shouldShowTranslationProgress(
  status: TranslationJobStatus,
  translatedPageCount: number,
): boolean {
  return (
    translatedPageCount > 0 &&
    (status === "TRANSLATION_QUEUED" ||
      status === "TRANSLATING" ||
      status === "FAILED")
  );
}


export function shouldRefreshJobStatus(status: TranslationJobStatus): boolean {
  return (
    status === "QUEUED" ||
    status === "PROCESSING" ||
    status === "TRANSLATION_QUEUED" ||
    status === "TRANSLATING"
  );
}
