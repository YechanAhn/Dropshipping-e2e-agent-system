import { ReactNode } from 'react';
import { Card } from './Card';

interface StatCardProps {
  label: string;
  value: string;
  subValue?: string;
  icon?: ReactNode;
  accent?: 'primary' | 'secondary' | 'success' | 'warning';
}

const accentClasses = {
  primary: 'bg-primary-soft text-primary',
  secondary: 'bg-secondary-soft text-secondary',
  success: 'bg-success-soft text-success',
  warning: 'bg-warning-soft text-warning',
};

export function StatCard({ label, value, subValue, icon, accent = 'primary' }: StatCardProps) {
  return (
    <Card className="p-6 hover:shadow-elevated transition-shadow duration-200">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-muted uppercase tracking-wider mb-2">{label}</p>
          <p className="text-2xl font-bold text-ink truncate">{value}</p>
          {subValue && (
            <p className="text-xs text-muted mt-1">{subValue}</p>
          )}
        </div>
        {icon && (
          <div className={['w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0', accentClasses[accent]].join(' ')}>
            {icon}
          </div>
        )}
      </div>
    </Card>
  );
}
