'use client';

import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, AlertTriangle, Save } from 'lucide-react';
import { Topbar } from '@/components/layout/Topbar';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Toggle } from '@/components/ui/Toggle';
import { Slider } from '@/components/ui/Slider';
import { Skeleton } from '@/components/ui/Skeleton';
import { useToast } from '@/components/ui/Toast';
import { getSettings, putSettings } from '@/lib/api';
import type { Settings } from '@/lib/types';

const DEFAULT_SETTINGS: Settings = {
  scoring_weights: { margin: 0.25, demand: 0.25, risk: 0.25, ops_cost: 0.25 },
  automation_flags: { auto_approve: false, auto_register: false, auto_order: false },
};

const WEIGHT_LABELS: Record<string, string> = {
  margin: '마진율',
  demand: '수요 점수',
  risk: '리스크',
  ops_cost: '운영 비용',
};

const FLAG_META = [
  {
    key: 'auto_approve' as const,
    label: '자동 승인 (auto_approve)',
    description: '후보 상품을 자동으로 승인합니다. 수동 검토 없이 진행됩니다.',
    danger: false,
  },
  {
    key: 'auto_register' as const,
    label: '자동 등록 (auto_register)',
    description: '승인된 상품을 네이버 스마트스토어에 자동으로 등록합니다.',
    danger: false,
  },
  {
    key: 'auto_order' as const,
    label: '자동 주문 (auto_order)',
    description: '⚠ 주의: 결제가 자동으로 처리됩니다. 반드시 충분한 검토 후 활성화하세요.',
    danger: true,
  },
];

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [pageStatus, setPageStatus] = useState<'loading' | 'error' | 'ready'>('loading');
  const [saving, setSaving] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const toast = useToast();

  const load = useCallback(async () => {
    setPageStatus('loading');
    try {
      const data = await getSettings();
      setSettings(data);
      setPageStatus('ready');
    } catch {
      setPageStatus('error');
      // show default so UI is usable offline
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  const weightSum = Object.values(settings.scoring_weights).reduce((s, v) => s + v, 0);
  const weightSumDisplay = (weightSum * 100).toFixed(0);
  const weightOk = Math.abs(weightSum - 1) < 0.001;

  const normalizeWeights = () => {
    const w = settings.scoring_weights;
    const sum = w.margin + w.demand + w.risk + w.ops_cost;
    if (sum === 0) return;
    const normalized: Settings['scoring_weights'] = {
      margin: w.margin / sum,
      demand: w.demand / sum,
      risk: w.risk / sum,
      ops_cost: w.ops_cost / sum,
    };
    setSettings((prev) => ({ ...prev, scoring_weights: normalized }));
    toast.info('가중치 정규화 완료', '합계가 1.00이 되도록 조정되었습니다');
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const saved = await putSettings(settings);
      setSettings(saved);
      toast.success('설정 저장 완료', '변경 사항이 반영되었습니다');
    } catch {
      toast.error('저장 실패', '백엔드에 연결할 수 없습니다');
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <Topbar title="설정" onRefresh={() => setRefreshKey((k) => k + 1)} />
      <main className="flex-1 p-8 max-w-3xl mx-auto w-full">

        {pageStatus === 'error' && (
          <div className="mb-6 flex items-center gap-3 bg-danger-soft border border-danger/20 rounded-2xl px-5 py-4 text-danger">
            <AlertCircle size={18} className="flex-shrink-0" />
            <div>
              <p className="text-sm font-semibold">백엔드에 연결할 수 없습니다</p>
              <p className="text-xs opacity-80 mt-0.5">기본값이 표시됩니다. 저장 시 연결이 필요합니다.</p>
            </div>
          </div>
        )}

        {/* Scoring weights */}
        <Card className="p-6 mb-6">
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-sm font-semibold text-ink">점수 가중치</h2>
            <div className="flex items-center gap-3">
              <span className={[
                'text-xs font-mono px-2 py-0.5 rounded-lg',
                weightOk ? 'bg-success-soft text-success' : 'bg-danger-soft text-danger',
              ].join(' ')}>
                합계 {weightSumDisplay}%
              </span>
              {!weightOk && (
                <button
                  onClick={normalizeWeights}
                  className="text-xs text-primary hover:underline font-medium"
                >
                  정규화
                </button>
              )}
            </div>
          </div>
          <p className="text-xs text-muted mb-6">4개 가중치의 합이 1.00이 되어야 합니다.</p>

          {pageStatus === 'loading' ? (
            <div className="space-y-4">
              {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-8 w-full" />)}
            </div>
          ) : (
            <div className="space-y-4">
              {(Object.keys(settings.scoring_weights) as Array<keyof Settings['scoring_weights']>).map((key) => (
                <Slider
                  key={key}
                  label={WEIGHT_LABELS[key] ?? key}
                  value={settings.scoring_weights[key]}
                  min={0}
                  max={1}
                  step={0.01}
                  onChange={(v) =>
                    setSettings((prev) => ({
                      ...prev,
                      scoring_weights: { ...prev.scoring_weights, [key]: v },
                    }))
                  }
                />
              ))}
            </div>
          )}
        </Card>

        {/* Automation flags */}
        <Card className="p-6 mb-6">
          <h2 className="text-sm font-semibold text-ink mb-1">자동화 플래그</h2>
          <p className="text-xs text-muted mb-6">각 항목을 활성화하면 해당 단계가 자동으로 실행됩니다.</p>

          {pageStatus === 'loading' ? (
            <div className="space-y-5">
              {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}
            </div>
          ) : (
            <div className="space-y-5">
              {FLAG_META.map(({ key, label, description, danger }) => (
                <div
                  key={key}
                  className={[
                    'p-4 rounded-2xl border',
                    danger && settings.automation_flags[key]
                      ? 'bg-danger-soft border-danger/30'
                      : 'bg-paper border-border',
                  ].join(' ')}
                >
                  {danger && settings.automation_flags[key] && (
                    <div className="flex items-center gap-2 mb-3 text-danger">
                      <AlertTriangle size={14} />
                      <span className="text-xs font-semibold">결제 자동화가 활성화되어 있습니다</span>
                    </div>
                  )}
                  <Toggle
                    checked={settings.automation_flags[key]}
                    onChange={(v) =>
                      setSettings((prev) => ({
                        ...prev,
                        automation_flags: { ...prev.automation_flags, [key]: v },
                      }))
                    }
                    label={label}
                    description={description}
                    danger={danger}
                  />
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Save */}
        <div className="flex justify-end">
          <Button
            variant="primary"
            size="lg"
            onClick={handleSave}
            loading={saving}
            disabled={pageStatus === 'loading'}
          >
            <Save size={16} />
            저장
          </Button>
        </div>
      </main>
    </>
  );
}
