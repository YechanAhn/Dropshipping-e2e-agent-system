'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  TrendingUp,
  ShoppingBag,
  Package,
  AlertCircle,
  BarChart2,
} from 'lucide-react';
import { Topbar } from '@/components/layout/Topbar';
import { StatCard } from '@/components/ui/StatCard';
import { Card } from '@/components/ui/Card';
import { StatusBadge } from '@/components/ui/Badge';
import { EmptyState } from '@/components/ui/EmptyState';
import { StatCardSkeleton, Skeleton } from '@/components/ui/Skeleton';
import { getAnalyticsSummary, getProducts, getSettings } from '@/lib/api';
import { formatKRW, formatNumber, formatPercent } from '@/lib/format';
import type { AnalyticsSummary, ProductOut, Settings, TrendingKeyword } from '@/lib/types';

type PageState = 'loading' | 'error' | 'ready';

interface DashData {
  analytics: AnalyticsSummary | null;
  products: ProductOut[];
  settings: Settings | null;
}

function getRevenueSummary(analytics: AnalyticsSummary | null): string {
  if (!analytics) return '—';
  const rev = analytics.revenue_summary;
  if (!rev) return '—';
  const totalKey = Object.keys(rev).find((k) => k.includes('total') || k.includes('revenue'));
  if (totalKey) return formatKRW(Number(rev[totalKey]));
  const vals = Object.values(rev);
  if (vals.length > 0) return formatKRW(Number(vals[0]));
  return '—';
}

function getKeywordDisplayName(kw: TrendingKeyword): string {
  return (kw.keyword as string | undefined) ??
    (Object.values(kw)[0] as string | undefined) ??
    '—';
}

export default function OverviewPage() {
  const [state, setState] = useState<PageState>('loading');
  const [data, setData] = useState<DashData>({ analytics: null, products: [], settings: null });
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(async () => {
    setState('loading');
    try {
      const [analytics, products, settings] = await Promise.allSettled([
        getAnalyticsSummary({ days: 30, keyword_limit: 10 }),
        getProducts({ limit: 500 }),
        getSettings(),
      ]);
      setData({
        analytics: analytics.status === 'fulfilled' ? analytics.value : null,
        products: products.status === 'fulfilled' ? products.value : [],
        settings: settings.status === 'fulfilled' ? settings.value : null,
      });
      setState('ready');
    } catch {
      setState('error');
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  const handleRefresh = () => setRefreshKey((k) => k + 1);

  const { analytics, products, settings } = data;

  const totalOrders = analytics
    ? Object.values(analytics.order_counts).reduce((s, v) => s + v, 0)
    : 0;

  const productStatusCounts = products.reduce<Record<string, number>>((acc, p) => {
    acc[p.status] = (acc[p.status] ?? 0) + 1;
    return acc;
  }, {});

  const automationFlags = settings?.automation_flags;

  return (
    <>
      <Topbar title="개요" onRefresh={handleRefresh} />
      <main className="flex-1 p-8 max-w-7xl mx-auto w-full">
        {state === 'error' && (
          <div className="mb-6 flex items-center gap-3 bg-danger-soft border border-danger/20 rounded-2xl px-5 py-4 text-danger">
            <AlertCircle size={18} className="flex-shrink-0" />
            <div>
              <p className="text-sm font-semibold">백엔드에 연결할 수 없습니다</p>
              <p className="text-xs opacity-80 mt-0.5">서버가 실행 중인지 확인하세요 (localhost:8000)</p>
            </div>
          </div>
        )}

        {/* Stat cards */}
        <section aria-label="핵심 지표" className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-8">
          {state === 'loading' ? (
            Array.from({ length: 4 }).map((_, i) => <StatCardSkeleton key={i} />)
          ) : (
            <>
              <StatCard
                label="총 매출 (30일)"
                value={getRevenueSummary(analytics)}
                subValue="최근 30일 기준"
                icon={<TrendingUp size={18} />}
                accent="primary"
              />
              <StatCard
                label="총 주문 수"
                value={formatNumber(totalOrders)}
                subValue="전체 상태 합산"
                icon={<ShoppingBag size={18} />}
                accent="secondary"
              />
              <StatCard
                label="상품 수"
                value={formatNumber(products.length)}
                subValue={`승인 ${formatNumber(productStatusCounts['approved'] ?? 0)}개`}
                icon={<Package size={18} />}
                accent="success"
              />
              <StatCard
                label="검토 대기"
                value={formatNumber(productStatusCounts['review'] ?? 0)}
                subValue="수동 검토 필요"
                icon={<BarChart2 size={18} />}
                accent="warning"
              />
            </>
          )}
        </section>

        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          {/* Order status */}
          <Card className="p-6 xl:col-span-1">
            <h2 className="text-sm font-semibold text-ink mb-4">주문 상태별 현황</h2>
            {state === 'loading' ? (
              <div className="space-y-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              </div>
            ) : !analytics || Object.keys(analytics.order_counts).length === 0 ? (
              <EmptyState title="주문 데이터 없음" description="아직 데이터가 없습니다" />
            ) : (
              <div className="flex flex-wrap gap-2">
                {Object.entries(analytics.order_counts).map(([status, count]) => (
                  <div key={status} className="flex items-center gap-2 bg-paper rounded-xl px-3 py-2 border border-border">
                    <StatusBadge status={status} />
                    <span className="text-sm font-semibold text-ink">{count}</span>
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* Trending keywords */}
          <Card className="p-6 xl:col-span-2">
            <h2 className="text-sm font-semibold text-ink mb-4">인기 트렌드 키워드</h2>
            {state === 'loading' ? (
              <div className="space-y-2">
                {Array.from({ length: 6 }).map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              </div>
            ) : !analytics || analytics.top_trending_keywords.length === 0 ? (
              <EmptyState title="키워드 데이터 없음" description="아직 데이터가 없습니다" />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="py-2 px-3 text-left text-xs font-semibold text-muted">#</th>
                      <th className="py-2 px-3 text-left text-xs font-semibold text-muted">키워드</th>
                      <th className="py-2 px-3 text-left text-xs font-semibold text-muted">검색량</th>
                      <th className="py-2 px-3 text-left text-xs font-semibold text-muted">카테고리</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {analytics.top_trending_keywords.slice(0, 10).map((kw, i) => (
                      <tr key={i} className="hover:bg-paper/60 transition-colors">
                        <td className="py-2 px-3 text-muted text-xs">{i + 1}</td>
                        <td className="py-2 px-3 font-medium text-ink">{getKeywordDisplayName(kw)}</td>
                        <td className="py-2 px-3 text-muted">
                          {kw.search_volume != null ? formatNumber(Number(kw.search_volume)) : '—'}
                        </td>
                        <td className="py-2 px-3 text-muted text-xs">{(kw.category as string | undefined) ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>

        {/* Automation status */}
        {state !== 'loading' && (
          <Card className="p-6 mt-6">
            <h2 className="text-sm font-semibold text-ink mb-4">자동화 플래그 상태</h2>
            {!automationFlags ? (
              <p className="text-sm text-muted">설정을 불러올 수 없습니다</p>
            ) : (
              <div className="flex flex-wrap gap-3">
                {[
                  { key: 'auto_approve', label: '자동 승인' },
                  { key: 'auto_register', label: '자동 등록' },
                  { key: 'auto_order', label: '자동 주문' },
                ].map(({ key, label }) => {
                  const active = automationFlags[key as keyof typeof automationFlags];
                  return (
                    <div
                      key={key}
                      className={[
                        'inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium border',
                        active
                          ? 'bg-success-soft text-success border-success/20'
                          : 'bg-paper text-muted border-border',
                      ].join(' ')}
                    >
                      <span className={['w-1.5 h-1.5 rounded-full', active ? 'bg-success' : 'bg-muted'].join(' ')} />
                      {label}
                      <span className="text-xs opacity-70">{active ? 'ON' : 'OFF'}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
        )}
      </main>
    </>
  );
}
