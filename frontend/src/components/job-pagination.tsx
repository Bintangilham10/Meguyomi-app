import Link from "next/link";

import type { JobPagination as JobPaginationData } from "@/types/job";


interface JobPaginationProps {
  pagination: JobPaginationData;
}


function pageHref(page: number): string {
  return page === 1 ? "/" : `/?page=${page}`;
}


export function JobPagination({ pagination }: JobPaginationProps) {
  if (pagination.totalPages <= 1) {
    return null;
  }
  const hasPrevious = pagination.page > 1;
  const hasNext = pagination.page < pagination.totalPages;

  return (
    <nav
      aria-label="Navigasi riwayat pekerjaan"
      className="mt-5 flex items-center justify-between gap-4"
    >
      {hasPrevious ? (
        <Link
          href={pageHref(pagination.page - 1)}
          className="border border-[var(--border-strong)] px-3 py-2 text-xs font-semibold transition hover:border-[var(--accent)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
          rel="prev"
        >
          Sebelumnya
        </Link>
      ) : (
        <span className="border border-[var(--border)] px-3 py-2 text-xs text-[var(--muted)] opacity-60">
          Sebelumnya
        </span>
      )}
      <span className="text-xs tabular-nums text-[var(--muted)]">
        Halaman {pagination.page} dari {pagination.totalPages}
      </span>
      {hasNext ? (
        <Link
          href={pageHref(pagination.page + 1)}
          className="border border-[var(--border-strong)] px-3 py-2 text-xs font-semibold transition hover:border-[var(--accent)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
          rel="next"
        >
          Berikutnya
        </Link>
      ) : (
        <span className="border border-[var(--border)] px-3 py-2 text-xs text-[var(--muted)] opacity-60">
          Berikutnya
        </span>
      )}
    </nav>
  );
}
