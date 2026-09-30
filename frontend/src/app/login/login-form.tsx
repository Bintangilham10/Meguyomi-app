"use client";

import { useActionState } from "react";

import { loginAction } from "./actions";


const initialState = { error: null };


export function LoginForm() {
  const [state, formAction, isPending] = useActionState(loginAction, initialState);

  return (
    <form action={formAction} className="login-form" aria-busy={isPending}>
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
          className="field-control"
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
          className="field-control"
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
        className="primary-action"
      >
        {isPending ? "Memeriksa..." : "Masuk ke studio"}
      </button>
    </form>
  );
}
