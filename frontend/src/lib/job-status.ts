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
    detail: "Seluruh halaman siap. Mulai terjemahan dengan mesin lokal.",
    tone: "ready",
  },
  TRANSLATION_QUEUED: {
    label: "Menunggu AI",
    detail: "Terjemahan sudah masuk antrean worker.",
    tone: "active",
  },
  TRANSLATING: {
    label: "Menerjemahkan",
    detail: "Mesin lokal sedang membaca dan menerjemahkan halaman manga.",
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

const qualityFailurePresentations: Record<string, JobStatusPresentation> = {
  RESULT_PLACEMENT_OVERLAP: {
    label: "Area teks saling bertumpuk",
    detail:
      "Sebagian area teks masih bertumpuk setelah dipindai ulang. Progres tersimpan. Pemindaian ulang dapat menghasilkan deteksi yang sama; halaman ini perlu diperiksa jika error berulang.",
    tone: "danger",
  },
  RESULT_SOURCE_MASK_FAILED: {
    label: "Teks sumber belum dapat dibersihkan",
    detail:
      "Batas teks sumber belum cukup akurat untuk dihapus dengan aman. Coba lagi untuk memindai ulang halaman ini.",
    tone: "danger",
  },
  RESULT_TEXT_FIT_FAILED: {
    label: "Teks belum muat dengan aman",
    detail:
      "Terjemahan belum muat di salah satu balon atau panel tanpa menutup gambar. Progres tersimpan. Periksa panjang teks di Bank terjemahan sebelum mencoba lagi; pemindaian ulang bisa menghasilkan area yang sama.",
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
        label: "Menunggu mesin lokal",
        detail:
          "Mesin lokal sedang sibuk, menunggu slot inferensi berikutnya.",
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
      detail: "Periksa LOCAL_AI_URL dan pastikan service local-ai serta modelnya sudah siap, lalu coba terjemahkan lagi.",
      tone: "danger",
    };
  }
  if (status === "FAILED" && failureCode === "AI_MODEL_NOT_READY") {
    return {
      label: "Model lokal belum siap",
      detail: "Selesaikan pemasangan model sesuai README, mulai ulang mesin lokal, lalu coba terjemahkan lagi.",
      tone: "danger",
    };
  }
  if (status === "FAILED" && failureCode === "AI_TRANSLATION_FAILED") {
    return {
      label: "Terjemahan AI gagal",
      detail: "Periksa model dan OCR pada service local-ai, lalu coba terjemahkan lagi.",
      tone: "danger",
    };
  }
  if (status === "FAILED" && failureCode === "AI_LANGUAGE_DETECTION_FAILED") {
    return {
      label: "Bahasa sumber belum dikenali",
      detail: "Teks pada halaman sampel belum cukup jelas atau bahasanya bercampur. Unggah ulang PDF dan pilih Jepang, Mandarin (sederhana), atau Mandarin (tradisional) secara manual.",
      tone: "danger",
    };
  }
  if (status === "FAILED" && failureCode === "AI_RATE_LIMITED") {
    return {
      label: "Mesin lokal sedang sibuk",
      detail: "Service local-ai sedang membatasi inferensi bersamaan. Tunggu pekerjaan selesai, lalu coba lagi.",
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
  if (status === "FAILED" && failureCode) {
    const qualityPresentation = qualityFailurePresentations[failureCode];
    if (qualityPresentation) {
      return qualityPresentation;
    }
  }
  if (
    status === "FAILED" &&
    failureCode === "RESULT_QUALITY_FAILED"
  ) {
    return {
      label: "Tata letak perlu dipindai ulang",
      detail: "Koordinat teks belum cukup aman. Coba terjemahkan lagi untuk memindai ulang halaman ini.",
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
