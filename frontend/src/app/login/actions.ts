"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { SESSION_COOKIE_NAME } from "@/lib/auth";
import type { LoginState } from "@/types/auth";


const SESSION_MAX_AGE_SECONDS = 86_400;


function getApiUrl(): string {
  return process.env.API_URL ?? "http://localhost:8000";
}


function extractSessionCookie(setCookieHeader: string | null): string | null {
  if (!setCookieHeader) {
    return null;
  }
  const match = setCookieHeader.match(/meguyomi_session=([^;]+)/);
  return match?.[1] ?? null;
}


export async function loginAction(
  _previousState: LoginState,
  formData: FormData,
): Promise<LoginState> {
  const username = formData.get("username");
  const password = formData.get("password");
  if (
    typeof username !== "string" ||
    typeof password !== "string" ||
    username.length < 1 ||
    username.length > 64 ||
    password.length < 1 ||
    password.length > 256
  ) {
    return { error: "Isi username dan password dengan benar." };
  }

  let response: Response;
  try {
    response = await fetch(`${getApiUrl()}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
      cache: "no-store",
    });
  } catch {
    return { error: "Layanan login sedang tidak tersedia." };
  }

  if (response.status === 429) {
    return { error: "Terlalu banyak percobaan. Coba lagi nanti." };
  }
  if (!response.ok) {
    return { error: "Username atau password salah." };
  }

  const sessionValue = extractSessionCookie(response.headers.get("set-cookie"));
  if (!sessionValue) {
    return { error: "Sesi login tidak dapat dibuat." };
  }

  const cookieStore = await cookies();
  cookieStore.set(SESSION_COOKIE_NAME, sessionValue, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
  redirect("/");
}
