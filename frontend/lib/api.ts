import type {
  ProductOut,
  OrderOut,
  AnalyticsSummary,
  Settings,
  HealthStatus,
} from './types';

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

// Where the FastAPI backend lives. Default '/api' uses the same-origin Next
// rewrite proxy (next.config.mjs). Set NEXT_PUBLIC_API_BASE to call the backend
// directly (e.g. http://localhost:8000) — recommended in production since the
// backend's trailing-slash routes survive without a proxy round-trip (CORS is
// enabled server-side).
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '/api';

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, text);
  }
  return res.json() as Promise<T>;
}

// Health
export async function getHealth(): Promise<HealthStatus> {
  return apiFetch<HealthStatus>('/health');
}

// Products
export async function getProducts(params?: {
  status?: string;
  limit?: number;
}): Promise<ProductOut[]> {
  const q = new URLSearchParams();
  if (params?.status) q.set('status', params.status);
  if (params?.limit != null) q.set('limit', String(params.limit));
  const qs = q.toString() ? `?${q.toString()}` : '';
  return apiFetch<ProductOut[]>(`/products/${qs}`);
}

export async function approveProduct(id: number): Promise<ProductOut> {
  return apiFetch<ProductOut>(`/products/${id}/approve`, { method: 'POST' });
}

export async function rejectProduct(id: number): Promise<ProductOut> {
  return apiFetch<ProductOut>(`/products/${id}/reject`, { method: 'POST' });
}

// Orders
export async function getOrders(params?: {
  status?: string;
  recent_hours?: number;
  limit?: number;
}): Promise<OrderOut[]> {
  const q = new URLSearchParams();
  if (params?.status) q.set('status', params.status);
  if (params?.recent_hours != null) q.set('recent_hours', String(params.recent_hours));
  if (params?.limit != null) q.set('limit', String(params.limit));
  const qs = q.toString() ? `?${q.toString()}` : '';
  return apiFetch<OrderOut[]>(`/orders/${qs}`);
}

// Analytics
export async function getAnalyticsSummary(params?: {
  days?: number;
  keyword_limit?: number;
}): Promise<AnalyticsSummary> {
  const q = new URLSearchParams();
  if (params?.days != null) q.set('days', String(params.days));
  if (params?.keyword_limit != null) q.set('keyword_limit', String(params.keyword_limit));
  const qs = q.toString() ? `?${q.toString()}` : '';
  return apiFetch<AnalyticsSummary>(`/analytics/summary${qs}`);
}

// Settings
export async function getSettings(): Promise<Settings> {
  return apiFetch<Settings>('/settings/');
}

export async function putSettings(body: Settings): Promise<Settings> {
  return apiFetch<Settings>('/settings/', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
}
