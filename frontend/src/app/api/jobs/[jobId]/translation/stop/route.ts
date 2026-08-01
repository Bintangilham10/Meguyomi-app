import { cookies } from "next/headers";

import { SESSION_COOKIE_NAME } from "@/lib/auth";


export const runtime = "nodejs";

const JOB_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;


function getApiUrl(): string {
  return process.env.API_URL ?? "http://localhost:8000";
}


function apiError(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message } }, { status });
}


export async function POST(
  _request: Request,
  { params }: { params: Promise<{ jobId: string }> },
): Promise<Response> {
  const session = (await cookies()).get(SESSION_COOKIE_NAME)?.value;
  if (!session) {
    return apiError(401, "NOT_AUTHENTICATED", "Sesi login tidak valid.");
  }
  const { jobId } = await params;
  if (!JOB_ID_PATTERN.test(jobId)) {
    return apiError(400, "INVALID_JOB_ID", "ID pekerjaan tidak valid.");
  }

  try {
    const response = await fetch(
      `${getApiUrl()}/jobs/${jobId}/translation/stop`,
      {
        method: "POST",
        headers: { Cookie: `${SESSION_COOKIE_NAME}=${session}` },
        cache: "no-store",
      },
    );
    const contentType = response.headers.get("content-type") ?? "application/json";
    return new Response(response.body, {
      status: response.status,
      headers: {
        "Content-Type": contentType,
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return apiError(
      502,
      "API_UNAVAILABLE",
      "Layanan penghentian terjemahan sedang tidak tersedia.",
    );
  }
}
