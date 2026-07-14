import { cookies } from "next/headers";

import { SESSION_COOKIE_NAME } from "@/lib/auth";
import { parseJobListResponse } from "@/lib/job-contract";
import type { TranslationJob } from "@/types/job";


export interface JobListResult {
  jobs: TranslationJob[];
  error: string | null;
}


function getApiUrl(): string {
  return process.env.API_URL ?? "http://localhost:8000";
}


export async function getJobs(): Promise<JobListResult> {
  const session = (await cookies()).get(SESSION_COOKIE_NAME)?.value;
  if (!session) {
    return { jobs: [], error: "Sesi login tidak valid." };
  }

  try {
    const response = await fetch(`${getApiUrl()}/jobs`, {
      headers: { Cookie: `${SESSION_COOKIE_NAME}=${session}` },
      cache: "no-store",
    });
    if (!response.ok) {
      return { jobs: [], error: "Riwayat pekerjaan tidak dapat dimuat." };
    }

    const jobs = parseJobListResponse(await response.json());
    if (!jobs) {
      return { jobs: [], error: "Respons riwayat pekerjaan tidak valid." };
    }
    return { jobs, error: null };
  } catch {
    return { jobs: [], error: "Layanan riwayat sedang tidak tersedia." };
  }
}
