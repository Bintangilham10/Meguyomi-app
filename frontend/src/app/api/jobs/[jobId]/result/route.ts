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


export async function GET(
  request: Request,
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
    const mode = new URL(request.url).searchParams.get("mode");
    const resultUrl = new URL(`${getApiUrl()}/jobs/${jobId}/result`);
    if (mode === "print" || mode === "preview") {
      resultUrl.searchParams.set("disposition", "inline");
    }
    const response = await fetch(resultUrl, {
      headers: { Cookie: `${SESSION_COOKIE_NAME}=${session}` },
      cache: "no-store",
    });
    const headers = new Headers({ "Cache-Control": "private, no-store" });
    for (const name of ["content-type", "content-disposition", "content-length"]) {
      const value = response.headers.get(name);
      if (value) {
        headers.set(name, value);
      }
    }
    return new Response(response.body, { status: response.status, headers });
  } catch {
    return apiError(502, "API_UNAVAILABLE", "PDF hasil tidak dapat diunduh.");
  }
}
