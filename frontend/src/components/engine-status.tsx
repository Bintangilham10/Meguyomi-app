"use client";

import { useEffect, useState } from "react";
import { StudioIcon } from "@/components/studio-icon";

export function EngineStatus() {
  const [status, setStatus] = useState<"checking" | "ready" | "unavailable">(
    "checking",
  );
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 12_000);
    let disposed = false;
    fetch("/api/memory/status", {
      signal: controller.signal,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Status unavailable");
        const data: unknown = await response.json();
        if (!disposed)
          setStatus(
            typeof data === "object" &&
              data !== null &&
              "ready" in data &&
              data.ready === true
              ? "ready"
              : "unavailable",
          );
      })
      .catch(() => {
        if (!disposed) setStatus("unavailable");
      })
      .finally(() => window.clearTimeout(timeout));
    return () => {
      disposed = true;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [revision]);

  return (
    <div className="signal-card signal-card-engine" data-status={status}>
      <span className="signal-icon">
        <StudioIcon name="shield" />
      </span>
      <span role="status">
        <strong>
          {status === "checking"
            ? "Memeriksa mesin lokal"
            : status === "ready"
              ? "Mesin lokal siap"
              : "Mesin belum siap"}
        </strong>
        <small>
          {status === "unavailable"
            ? "Periksa layanan lokal, lalu cek lagi."
            : "Tanpa API key. Diproses di server lokal."}
        </small>
      </span>
      {status === "unavailable" ? (
        <button
          type="button"
          className="status-retry"
          onClick={() => {
            setStatus("checking");
            setRevision((value) => value + 1);
          }}
        >
          Cek lagi
        </button>
      ) : (
        <span className="status-indicator" aria-hidden="true" />
      )}
    </div>
  );
}
