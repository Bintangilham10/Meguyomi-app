import { cookies } from "next/headers";

import type { AuthUser } from "@/types/auth";


export const SESSION_COOKIE_NAME = "meguyomi_session";


function getApiUrl(): string {
  return process.env.API_URL ?? "http://localhost:8000";
}


export async function getCurrentUser(): Promise<AuthUser | null> {
  const sessionCookie = (await cookies()).get(SESSION_COOKIE_NAME)?.value;
  if (!sessionCookie) {
    return null;
  }

  try {
    const response = await fetch(`${getApiUrl()}/auth/me`, {
      headers: { Cookie: `${SESSION_COOKIE_NAME}=${sessionCookie}` },
      cache: "no-store",
    });
    if (!response.ok) {
      return null;
    }

    const body: unknown = await response.json();
    if (
      typeof body !== "object" ||
      body === null ||
      !("username" in body) ||
      typeof body.username !== "string"
    ) {
      return null;
    }
    return { username: body.username };
  } catch {
    return null;
  }
}
