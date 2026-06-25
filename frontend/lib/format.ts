// Backend sends DECIMAL fields as JSON strings (e.g. "12300.00"); coerce safely
// so number formatting never throws on a stringified decimal.
function toNum(value: number | string | null | undefined): number | null {
  if (value == null || value === '') return null;
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

export function formatKRW(value: number | string | null | undefined): string {
  const n = toNum(value);
  if (n == null) return '—';
  return new Intl.NumberFormat('ko-KR', {
    style: 'currency',
    currency: 'KRW',
    maximumFractionDigits: 0,
  }).format(n);
}

export function formatNumber(value: number | string | null | undefined): string {
  const n = toNum(value);
  if (n == null) return '—';
  return new Intl.NumberFormat('ko-KR').format(n);
}

/** Format a 0..1 ratio as a percentage, e.g. 0.52 -> "52.0%". */
export function formatPercent(value: number | string | null | undefined, decimals = 1): string {
  const n = toNum(value);
  if (n == null) return '—';
  return `${(n * 100).toFixed(decimals)}%`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  try {
    return new Intl.DateTimeFormat('ko-KR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(value));
  } catch {
    return value;
  }
}

export function formatScore(value: number | string | null | undefined): string {
  const n = toNum(value);
  if (n == null) return '—';
  return n.toFixed(2);
}
