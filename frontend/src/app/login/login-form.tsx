"use client";

import { useActionState } from "react";

import { loginAction } from "./actions";


const initialState = { error: null };


export function LoginForm() {
  const [state, formAction, isPending] = useActionState(loginAction, initialState);

  return (
    <form action={formAction} className="mt-8 space-y-5">
      <div>
        <label htmlFor="username" className="block text-sm font-bold">
          Username
        </label>
        <input
          id="username"
          name="username"
          type="text"
          autoComplete="username"
          required
          maxLength={64}
          autoFocus
          className="mt-2 w-full rounded-[10px] border border-[var(--border-strong)] bg-[var(--surface-strong)] px-4 py-3.5 text-base outline-none transition focus:border-[var(--ink)] focus:ring-2 focus:ring-[var(--accent-soft)]"
        />
      </div>

      <div>
        <label htmlFor="password" className="block text-sm font-bold">
          Password
        </label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          maxLength={256}
          className="mt-2 w-full rounded-[10px] border border-[var(--border-strong)] bg-[var(--surface-strong)] px-4 py-3.5 text-base outline-none transition focus:border-[var(--ink)] focus:ring-2 focus:ring-[var(--accent-soft)]"
        />
      </div>

      {state.error ? (
        <p
          role="alert"
          className="rounded-[10px] bg-[var(--accent-wash)] px-4 py-3 text-sm font-medium text-[var(--danger)]"
        >
          {state.error}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={isPending}
        className="brand-shadow min-h-12 w-full rounded-[10px] border border-[var(--ink)] bg-[var(--accent)] px-4 py-3 font-bold text-white transition focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-60 disabled:shadow-none disabled:transform-none"
      >
        {isPending ? "Memeriksa..." : "Masuk"}
      </button>
    </form>
  );
}
