import { cookies } from "next/headers";

import { SESSION_COOKIE_NAME } from "@/lib/auth";
import { parseJobListResponse } from "@/lib/job-contract";
import type { JobPagination, TranslationJob } from "@/types/job";


export interface JobListResult {
  jobs: TranslationJob[];
  pagination: JobPagination;
  error: string | null;
}


const JOB_PAGE_SIZE = 10;


function emptyPagination(page: number): JobPagination {
  return {
    page,
    pageSize: JOB_PAGE_SIZE,
    totalItems: 0,
    totalPages: 0,
  };
}


function getApiUrl(): string {
  return process.env.API_URL ?? "http://localhost:8000";
}


export async function getJobs(page: number): Promise<JobListResult> {
  const session = (await cookies()).get(SESSION_COOKIE_NAME)?.value;
  if (!session) {
    return {
      jobs: [],
      pagination: emptyPagination(page),
      error: "Sesi login tidak valid.",
    };
  }

  try {
    const query = new URLSearchParams({
      page: String(page),
      pageSize: String(JOB_PAGE_SIZE),
    });
    const response = await fetch(`${getApiUrl()}/jobs?${query}`, {
      headers: { Cookie: `${SESSION_COOKIE_NAME}=${session}` },
      cache: "no-store",
    });
    if (!response.ok) {
      return {
        jobs: [],
        pagination: emptyPagination(page),
        error: "Riwayat pekerjaan tidak dapat dimuat.",
      };
    }

    const result = parseJobListResponse(await response.json());
    if (!result) {
      return {
        jobs: [],
        pagination: emptyPagination(page),
        error: "Respons riwayat pekerjaan tidak valid.",
      };
    }
    return {
      jobs: result.data,
      pagination: result.pagination,
      error: null,
    };
  } catch {
    return {
      jobs: [],
      pagination: emptyPagination(page),
      error: "Layanan riwayat sedang tidak tersedia.",
    };
  }
}
