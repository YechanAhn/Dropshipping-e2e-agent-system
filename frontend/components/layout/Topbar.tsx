'use client';

import { useEffect, useState, useCallback } from 'react';
import { RefreshCw, Wifi, WifiOff } from 'lucide-react';
import { getHealth } from '@/lib/api';

interface TopbarProps {
  title: string;
  onRefresh?: () => void;
}

type HealthState = 'unknown' | 'ok' | 'error';

export function Topbar({ title, onRefresh }: TopbarProps) {
  const [health, setHealth] = useState<HealthState>('unknown');
  const [refreshing, setRefreshing] = useState(false);

  const checkHealth = useCallback(async () => {
    try {
      await getHealth();
      setHealth('ok');
    } catch {
      setHealth('error');
    }
  }, []);

  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 30_000);
    return () => clearInterval(interval);
  }, [checkHealth]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await checkHealth();
    onRefresh?.();
    setTimeout(() => setRefreshing(false), 600);
  };

  return (
    <header className="h-14 bg-surface border-b border-border flex items-center justify-between px-8 sticky top-0 z-10">
      <h1 className="text-base font-semibold text-ink">{title}</h1>
      <div className="flex items-center gap-3">
        {/* Health pill */}
        <div
          className={[
            'inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium transition-colors duration-300',
            health === 'ok'
              ? 'bg-success-soft text-success'
              : health === 'error'
              ? 'bg-danger-soft text-danger'
              : 'bg-paper text-muted',
          ].join(' ')}
          title={health === 'ok' ? '백엔드 연결됨' : health === 'error' ? '백엔드 오프라인' : '연결 확인중'}
        >
          {health === 'ok' ? (
            <Wifi size={12} />
          ) : health === 'error' ? (
            <WifiOff size={12} />
          ) : (
            <span className="w-3 h-3 rounded-full bg-muted/40 animate-pulse" />
          )}
          {health === 'ok' ? '정상' : health === 'error' ? '오프라인' : '확인중'}
        </div>

        {/* Refresh */}
        <button
          onClick={handleRefresh}
          aria-label="새로고침"
          className="w-8 h-8 rounded-xl flex items-center justify-center text-muted hover:text-ink hover:bg-paper transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          <RefreshCw size={15} className={refreshing ? 'animate-spin' : ''} />
        </button>
      </div>
    </header>
  );
}
