import type {
  TranslationJobStatus,
  TranslationWaitReason,
} from "@/types/job";


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
  TRANSLATION_RETRY_WAIT: {
    label: "Menunggu layanan AI",
    detail: "Permintaan akan dicoba kembali secara otomatis.",
    tone: "active",
  },
  TRANSLATION_STOPPING: {
    label: "Menghentikan",
    detail: "Worker menyelesaikan checkpoint terakhir dan menyusun PDF parsial.",
    tone: "active",
  },
  TRANSLATION_STOPPED: {
    label: "Dihentikan",
    detail: "Checkpoint tersimpan dan dapat dilanjutkan kapan saja.",
    tone: "ready",
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
  waitReason?: TranslationWaitReason | null,
): JobStatusPresentation {
  if (status === "TRANSLATION_RETRY_WAIT") {
    if (waitReason === "rate_limited") {
      return {
        label: "Menunggu batas Gemini",
        detail:
          "Batas kuota Gemini tercapai, menunggu percobaan berikutnya.",
        tone: "active",
      };
    }
    if (waitReason === "service_unavailable") {
      return {
        label: "Menunggu layanan AI",
        detail: "Layanan AI sedang terganggu, akan dicoba kembali.",
        tone: "active",
      };
    }
    if (waitReason === "worker_recovery") {
      return {
        label: "Menunggu worker",
        detail: "Proses worker terhenti, akan dilanjutkan otomatis.",
        tone: "active",
      };
    }
    if (waitReason === "queue_unavailable") {
      return {
        label: "Menunggu antrean",
        detail: "Antrean sementara tidak tersedia, akan dicoba kembali.",
        tone: "active",
      };
    }
  }
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
  if (status === "FAILED" && failureCode === "AI_SERVICE_UNAVAILABLE") {
    return {
      label: "Layanan AI belum tersedia",
      detail: "Koneksi ke layanan AI belum berhasil. Coba lagi nanti.",
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
      status === "TRANSLATION_RETRY_WAIT" ||
      status === "TRANSLATION_STOPPING" ||
      status === "TRANSLATION_STOPPED" ||
      status === "FAILED")
  );
}


export function shouldRefreshJobStatus(status: TranslationJobStatus): boolean {
  return (
    status === "QUEUED" ||
    status === "PROCESSING" ||
    status === "TRANSLATION_QUEUED" ||
    status === "TRANSLATING" ||
    status === "TRANSLATION_RETRY_WAIT" ||
    status === "TRANSLATION_STOPPING"
  );
}
