import { cookies } from "next/headers";
import { SESSION_COOKIE_NAME } from "@/lib/auth";

export const runtime = "nodejs";
type Context = { params: Promise<{ path?: string[] }> };

async function forward(request: Request, context: Context): Promise<Response> {
  const session = (await cookies()).get(SESSION_COOKIE_NAME)?.value;
  if (!session) return Response.json({ error: "Sesi login tidak valid." }, { status: 401 });
  const path = ((await context.params).path ?? []).join("/");
  const allowed = request.method === "GET" ? /^(|status|export|suggestions)$/ : request.method === "POST" ? /^(|import)$/ : /^\d+$/;
  if (!allowed.test(path)) return new Response(null, { status: 404 });
  const url = new URL(request.url);
  const query = new URLSearchParams();
  for (const key of ["page", "q", "source_language"]) {
    const value = url.searchParams.get(key);
    if (value !== null) query.set(key, value);
  }
  try {
    let body: string | undefined;
    if (request.method === "POST") {
      // Bound imports before forwarding them to the authenticated API.
      const reader = request.body?.getReader();
      if (!reader) return new Response(null, { status: 400 });
      const chunks: Uint8Array[] = [];
      let size = 0;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > 4 * 1024 * 1024) {
          await reader.cancel();
          return Response.json({ error: "Impor maksimal 4 MB per batch." }, { status: 413 });
        }
        chunks.push(value);
      }
      body = Buffer.concat(chunks).toString("utf8");
    }
    const response = await fetch(`${process.env.API_URL ?? "http://localhost:8000"}/memory${path ? `/${path}` : ""}?${query}`, {
      method: request.method,
      headers: { Cookie: `${SESSION_COOKIE_NAME}=${session}`, "Content-Type": "application/json" },
      body, cache: "no-store",
    });
    const headers = new Headers({ "Cache-Control": "no-store" });
    for (const name of ["content-type", "content-disposition"]) {
      const value = response.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new Response(response.body, { status: response.status, headers });
  } catch {
    return Response.json({ error: "Bank terjemahan belum dapat dihubungi." }, { status: 502 });
  }
}

export const GET = forward;
export const POST = forward;
export const DELETE = forward;
