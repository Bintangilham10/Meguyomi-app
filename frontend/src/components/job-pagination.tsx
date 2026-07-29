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
      className="mt-6 flex items-center justify-between gap-3 border-t border-[var(--border)] pt-5"
    >
      {hasPrevious ? (
        <Link
          href={pageHref(pagination.page - 1)}
          className="rounded-[10px] border border-[var(--ink)] bg-[var(--surface-strong)] px-3 py-2 text-xs font-bold transition hover:bg-[var(--ink)] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
          rel="prev"
        >
          Sebelumnya
        </Link>
      ) : (
        <span className="rounded-[10px] border border-[var(--border)] px-3 py-2 text-xs text-[var(--muted)] opacity-60">
          Sebelumnya
        </span>
      )}
      <span className="text-center text-xs font-medium tabular-nums text-[var(--muted)]">
        Halaman {pagination.page} dari {pagination.totalPages}
      </span>
      {hasNext ? (
        <Link
          href={pageHref(pagination.page + 1)}
          className="rounded-[10px] border border-[var(--ink)] bg-[var(--surface-strong)] px-3 py-2 text-xs font-bold transition hover:bg-[var(--ink)] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
          rel="next"
        >
          Berikutnya
        </Link>
      ) : (
        <span className="rounded-[10px] border border-[var(--border)] px-3 py-2 text-xs text-[var(--muted)] opacity-60">
          Berikutnya
        </span>
      )}
    </nav>
  );
}
