import { cookies } from "next/headers";

import { SESSION_COOKIE_NAME } from "@/lib/auth";
import { exceedsProxyRequestLimit } from "@/lib/upload-policy";


export const runtime = "nodejs";

type StreamingRequestInit = RequestInit & { duplex: "half" };


function getApiUrl(): string {
  return process.env.API_URL ?? "http://localhost:8000";
}


function apiError(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message } }, { status });
}


async function getSessionHeader(): Promise<Record<string, string> | null> {
  const session = (await cookies()).get(SESSION_COOKIE_NAME)?.value;
  if (!session) {
    return null;
  }
  return { Cookie: `${SESSION_COOKIE_NAME}=${session}` };
}


function forwardResponse(response: Response): Response {
  const contentType = response.headers.get("content-type");
  const headers = new Headers({ "Cache-Control": "no-store" });
  if (contentType) {
    headers.set("Content-Type", contentType);
  }
  return new Response(response.body, { status: response.status, headers });
}


export async function GET(): Promise<Response> {
  const headers = await getSessionHeader();
  if (!headers) {
    return apiError(401, "NOT_AUTHENTICATED", "Sesi login tidak valid.");
  }

  try {
    const response = await fetch(`${getApiUrl()}/jobs`, {
      headers,
      cache: "no-store",
    });
    return forwardResponse(response);
  } catch {
    return apiError(502, "API_UNAVAILABLE", "Layanan upload sedang tidak tersedia.");
  }
}


export async function POST(request: Request): Promise<Response> {
  const headers = await getSessionHeader();
  if (!headers) {
    return apiError(401, "NOT_AUTHENTICATED", "Sesi login tidak valid.");
  }

  const contentType = request.headers.get("content-type");
  if (!contentType?.toLowerCase().startsWith("multipart/form-data;")) {
    return apiError(415, "INVALID_FILE_TYPE", "File harus dikirim sebagai PDF.");
  }
  if (exceedsProxyRequestLimit(request.headers.get("content-length"))) {
    return apiError(413, "FILE_TOO_LARGE", "Ukuran PDF maksimal 50 MB.");
  }

  try {
    const init: StreamingRequestInit = {
      method: "POST",
      headers: { ...headers, "Content-Type": contentType },
      body: request.body,
      cache: "no-store",
      duplex: "half",
    };
    const response = await fetch(`${getApiUrl()}/jobs`, init);
    return forwardResponse(response);
  } catch {
    return apiError(502, "API_UNAVAILABLE", "Layanan upload sedang tidak tersedia.");
  }
}
