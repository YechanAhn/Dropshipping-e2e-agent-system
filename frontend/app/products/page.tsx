'use client';

import { useCallback, useEffect, useState, useTransition } from 'react';
import { Package, AlertCircle, CheckCircle, XCircle } from 'lucide-react';
import { Topbar } from '@/components/layout/Topbar';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { StatusBadge } from '@/components/ui/Badge';
import { EmptyState } from '@/components/ui/EmptyState';
import { Skeleton } from '@/components/ui/Skeleton';
import { useToast } from '@/components/ui/Toast';
import { getProducts, approveProduct, rejectProduct } from '@/lib/api';
import { formatKRW, formatPercent, formatScore } from '@/lib/format';
import type { ProductOut } from '@/lib/types';

const STATUS_FILTERS = [
  { value: '', label: '전체' },
  { value: 'candidate', label: '후보' },
  { value: 'review', label: '검토중' },
  { value: 'approved', label: '승인' },
  { value: 'rejected', label: '거절' },
  { value: 'registered', label: '등록됨' },
];

function ScoreBar({ value, max = 1, color = 'bg-primary' }: { value: number | null; max?: number; color?: string }) {
  if (value == null) return <span className="text-xs text-muted">—</span>;
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-border rounded-full overflow-hidden">
        <div className={[color, 'h-full rounded-full transition-all'].join(' ')} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-muted font-mono">{formatScore(value)}</span>
    </div>
  );
}

export default function ProductsPage() {
  const [products, setProducts] = useState<ProductOut[]>([]);
  const [status, setStatus] = useState<'loading' | 'error' | 'ready'>('loading');
  const [filter, setFilter] = useState('');
  const [actioning, setActioning] = useState<Record<number, 'approve' | 'reject' | null>>({});
  const [, startTransition] = useTransition();
  const toast = useToast();
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(async () => {
    setStatus('loading');
    try {
      const data = await getProducts({ status: filter || undefined, limit: 200 });
      setProducts(data);
      setStatus('ready');
    } catch {
      setStatus('error');
    }
  }, [filter]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  const handleApprove = async (product: ProductOut) => {
    setActioning((prev) => ({ ...prev, [product.id]: 'approve' }));
    // optimistic update
    setProducts((prev) =>
      prev.map((p) => (p.id === product.id ? { ...p, status: 'approved' } : p)),
    );
    try {
      const updated = await approveProduct(product.id);
      setProducts((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
      toast.success('상품 승인 완료', `${updated.product_name_ko ?? updated.product_name_en ?? String(updated.id)} 승인되었습니다`);
    } catch {
      // rollback
      setProducts((prev) =>
        prev.map((p) => (p.id === product.id ? product : p)),
      );
      toast.error('승인 실패', '다시 시도해주세요');
    } finally {
      setActioning((prev) => ({ ...prev, [product.id]: null }));
    }
  };

  const handleReject = async (product: ProductOut) => {
    setActioning((prev) => ({ ...prev, [product.id]: 'reject' }));
    setProducts((prev) =>
      prev.map((p) => (p.id === product.id ? { ...p, status: 'rejected' } : p)),
    );
    try {
      const updated = await rejectProduct(product.id);
      setProducts((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
      toast.warning('상품 거절됨', `${updated.product_name_ko ?? updated.product_name_en ?? String(updated.id)} 거절되었습니다`);
    } catch {
      setProducts((prev) =>
        prev.map((p) => (p.id === product.id ? product : p)),
      );
      toast.error('거절 실패', '다시 시도해주세요');
    } finally {
      setActioning((prev) => ({ ...prev, [product.id]: null }));
    }
  };

  return (
    <>
      <Topbar title="상품 관리" onRefresh={() => { startTransition(() => setRefreshKey((k) => k + 1)); }} />
      <main className="flex-1 p-8 max-w-7xl mx-auto w-full">

        {/* Error banner */}
        {status === 'error' && (
          <div className="mb-6 flex items-center gap-3 bg-danger-soft border border-danger/20 rounded-2xl px-5 py-4 text-danger">
            <AlertCircle size={18} className="flex-shrink-0" />
            <p className="text-sm font-semibold">백엔드에 연결할 수 없습니다</p>
          </div>
        )}

        {/* Filter chips */}
        <div className="flex gap-2 flex-wrap mb-6" role="group" aria-label="상태 필터">
          {STATUS_FILTERS.map(({ value, label }) => (
            <button
              key={value}
              onClick={() => setFilter(value)}
              className={[
                'px-4 py-1.5 rounded-full text-sm font-medium transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary',
                filter === value
                  ? 'bg-primary text-white shadow-sm'
                  : 'bg-surface text-muted border border-border hover:border-primary/40 hover:text-ink',
              ].join(' ')}
              aria-pressed={filter === value}
            >
              {label}
              {filter === value && products.length > 0 && (
                <span className="ml-1.5 text-xs opacity-80">({products.length})</span>
              )}
            </button>
          ))}
        </div>

        <Card>
          {status === 'loading' ? (
            <div className="p-6 space-y-3">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : products.length === 0 ? (
            <EmptyState
              icon={<Package size={24} />}
              title="상품이 없습니다"
              description="아직 데이터가 없습니다"
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border">
                    {['상품명', 'ALI 원가', '네이버 최저가', '판매가', '마진율', '우선순위', '수요', '상태', '액션'].map((h) => (
                      <th key={h} className="py-3 px-4 text-left text-xs font-semibold text-muted uppercase tracking-wider whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {products.map((product) => {
                    const name = product.product_name_ko ?? product.product_name_en ?? `#${product.id}`;
                    const isActioning = !!actioning[product.id];
                    const canAction = product.status === 'review' || product.status === 'candidate';
                    return (
                      <tr key={product.id} className="hover:bg-paper/60 transition-colors">
                        <td className="py-3 px-4">
                          <p className="font-medium text-ink truncate max-w-[180px]" title={name}>{name}</p>
                          <p className="text-xs text-muted mt-0.5">{product.category_naver ?? product.category_ali ?? '—'}</p>
                        </td>
                        <td className="py-3 px-4 text-ink">{formatKRW(product.price_ali_krw)}</td>
                        <td className="py-3 px-4">
                          {product.naver_catalog_lowest != null ? (
                            <>
                              <span className="text-ink font-medium">{formatKRW(product.naver_catalog_lowest)}</span>
                              {product.naver_price_min_market != null &&
                                product.naver_price_min_market !== product.naver_catalog_lowest && (
                                  <span className="block text-xs text-muted mt-0.5">
                                    시장 {formatKRW(product.naver_price_min_market)}
                                  </span>
                                )}
                            </>
                          ) : (
                            <span className="text-xs text-muted">—</span>
                          )}
                        </td>
                        <td className="py-3 px-4">
                          <span className="text-ink font-medium">{formatKRW(product.price_naver)}</span>
                          <div className="mt-0.5">
                            {product.is_price_lowest ? (
                              <span className="inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded bg-success-soft text-success">
                                최저가 보유
                              </span>
                            ) : product.badge_at_risk ? (
                              <span className="inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded bg-danger-soft text-danger">
                                최저가 아님{product.price_gap != null ? ` +${formatKRW(product.price_gap)}` : ''}
                              </span>
                            ) : null}
                          </div>
                        </td>
                        <td className="py-3 px-4">
                          <span className={[
                            'text-sm font-semibold',
                            (product.margin_rate ?? 0) >= 0.3 ? 'text-success' : (product.margin_rate ?? 0) >= 0.15 ? 'text-warning' : 'text-danger',
                          ].join(' ')}>
                            {formatPercent(product.margin_rate)}
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          <ScoreBar value={product.priority_score} color="bg-primary" />
                        </td>
                        <td className="py-3 px-4">
                          <ScoreBar value={product.demand_score} color="bg-secondary" />
                        </td>
                        <td className="py-3 px-4">
                          <StatusBadge status={product.status} />
                        </td>
                        <td className="py-3 px-4">
                          {canAction ? (
                            <div className="flex items-center gap-2">
                              <button
                                onClick={() => handleApprove(product)}
                                disabled={isActioning}
                                title="승인"
                                aria-label={`${name} 승인`}
                                className="w-7 h-7 rounded-lg flex items-center justify-center bg-success-soft text-success hover:bg-success hover:text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                              >
                                <CheckCircle size={14} />
                              </button>
                              <button
                                onClick={() => handleReject(product)}
                                disabled={isActioning}
                                title="거절"
                                aria-label={`${name} 거절`}
                                className="w-7 h-7 rounded-lg flex items-center justify-center bg-danger-soft text-danger hover:bg-danger hover:text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                              >
                                <XCircle size={14} />
                              </button>
                            </div>
                          ) : (
                            <span className="text-xs text-muted">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </main>
    </>
  );
}
