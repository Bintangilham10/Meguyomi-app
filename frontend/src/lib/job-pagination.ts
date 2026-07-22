const MAX_JOB_PAGE = 10_000;


export function parseJobPage(
  value: string | string[] | undefined,
): number {
  if (typeof value !== "string" || !/^\d+$/.test(value)) {
    return 1;
  }
  const page = Number(value);
  if (!Number.isSafeInteger(page) || page < 1 || page > MAX_JOB_PAGE) {
    return 1;
  }
  return page;
}
