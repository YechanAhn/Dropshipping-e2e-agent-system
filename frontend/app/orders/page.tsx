'use client';

import { useCallback, useEffect, useState, useTransition } from 'react';
import { ShoppingCart, AlertCircle, Info } from 'lucide-react';
import { Topbar } from '@/components/layout/Topbar';
import { Card } from '@/components/ui/Card';
import { StatusBadge } from '@/components/ui/Badge';
import { EmptyState } from '@/components/ui/EmptyState';
import { Skeleton } from '@/components/ui/Skeleton';
import { getOrders } from '@/lib/api';
import { formatKRW, formatDate } from '@/lib/format';
import type { OrderOut } from '@/lib/types';

const STATUS_FILTERS = [
  { value: '', label: '전체' },
  { value: 'pending', label: '대기' },
  { value: 'processing', label: '처리중' },
  { value: 'completed', label: '완료' },
  { value: 'cancelled', label: '취소' },
];

const HOUR_FILTERS = [
  { value: '', label: '전체 기간' },
  { value: '24', label: '최근 24시간' },
  { value: '72', label: '최근 3일' },
  { value: '168', label: '최근 7일' },
];

export default function OrdersPage() {
  const [orders, setOrders] = useState<OrderOut[]>([]);
  const [pageStatus, setPageStatus] = useState<'loading' | 'error' | 'ready'>('loading');
  const [statusFilter, setStatusFilter] = useState('');
  const [hoursFilter, setHoursFilter] = useState('');
  const [, startTransition] = useTransition();
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(async () => {
    setPageStatus('loading');
    try {
      const data = await getOrders({
        status: statusFilter || undefined,
        recent_hours: hoursFilter ? parseInt(hoursFilter, 10) : undefined,
        limit: 100,
      });
      setOrders(data);
      setPageStatus('ready');
    } catch {
      setPageStatus('error');
    }
  }, [statusFilter, hoursFilter]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  return (
    <>
      <Topbar title="주문 관리" onRefresh={() => { startTransition(() => setRefreshKey((k) => k + 1)); }} />
      <main className="flex-1 p-8 max-w-7xl mx-auto w-full">

        {/* HITL info banner */}
        <div className="mb-6 flex items-start gap-3 bg-secondary-soft border border-secondary/20 rounded-2xl px-5 py-4 text-secondary">
          <Info size={18} className="flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold">결제는 수동 처리(HITL)</p>
            <p className="text-xs opacity-80 mt-0.5">
              자동 주문 결제는 현재 비활성화 상태입니다. 주문 완료를 위해 수동 확인이 필요합니다.
            </p>
          </div>
        </div>

        {/* Error banner */}
        {pageStatus === 'error' && (
          <div className="mb-6 flex items-center gap-3 bg-danger-soft border border-danger/20 rounded-2xl px-5 py-4 text-danger">
            <AlertCircle size={18} className="flex-shrink-0" />
            <p className="text-sm font-semibold">백엔드에 연결할 수 없습니다</p>
          </div>
        )}

        {/* Filters */}
        <div className="flex flex-wrap gap-4 mb-6">
          <div className="flex gap-2 flex-wrap" role="group" aria-label="주문 상태 필터">
            {STATUS_FILTERS.map(({ value, label }) => (
              <button
                key={value}
                onClick={() => setStatusFilter(value)}
                className={[
                  'px-4 py-1.5 rounded-full text-sm font-medium transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary',
                  statusFilter === value
                    ? 'bg-primary text-white shadow-sm'
                    : 'bg-surface text-muted border border-border hover:border-primary/40 hover:text-ink',
                ].join(' ')}
                aria-pressed={statusFilter === value}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="flex gap-2 flex-wrap" role="group" aria-label="기간 필터">
            {HOUR_FILTERS.map(({ value, label }) => (
              <button
                key={value}
                onClick={() => setHoursFilter(value)}
                className={[
                  'px-4 py-1.5 rounded-full text-sm font-medium transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-secondary',
                  hoursFilter === value
                    ? 'bg-secondary text-white shadow-sm'
                    : 'bg-surface text-muted border border-border hover:border-secondary/40 hover:text-ink',
                ].join(' ')}
                aria-pressed={hoursFilter === value}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <Card>
          {pageStatus === 'loading' ? (
            <div className="p-6 space-y-3">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : orders.length === 0 ? (
            <EmptyState
              icon={<ShoppingCart size={24} />}
              title="주문이 없습니다"
              description="아직 데이터가 없습니다"
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border">
                    {['네이버 주문번호', '상품 ID', '수량', '총액', '상태', '생성일'].map((h) => (
                      <th key={h} className="py-3 px-4 text-left text-xs font-semibold text-muted uppercase tracking-wider whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {orders.map((order) => (
                    <tr key={order.id} className="hover:bg-paper/60 transition-colors">
                      <td className="py-3 px-4">
                        <span className="font-mono text-xs bg-paper border border-border px-2 py-0.5 rounded-lg text-ink">
                          {order.naver_order_id}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-muted">#{order.product_id}</td>
                      <td className="py-3 px-4 font-medium text-ink">{order.quantity}개</td>
                      <td className="py-3 px-4 font-semibold text-ink">{formatKRW(order.total_price)}</td>
                      <td className="py-3 px-4">
                        <StatusBadge status={order.status} />
                      </td>
                      <td className="py-3 px-4 text-muted text-xs">{formatDate(order.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {orders.length > 0 && pageStatus === 'ready' && (
          <p className="text-xs text-muted mt-3 text-right">{orders.length}개 주문 표시 중</p>
        )}
      </main>
    </>
  );
}
