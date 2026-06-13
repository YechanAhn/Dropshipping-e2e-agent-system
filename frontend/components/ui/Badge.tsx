import { HTMLAttributes } from 'react';

type BadgeVariant =
  | 'default'
  | 'candidate'
  | 'review'
  | 'approved'
  | 'rejected'
  | 'registered'
  | 'pending'
  | 'processing'
  | 'completed'
  | 'cancelled'
  | 'success'
  | 'warning'
  | 'danger';

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

const variantClasses: Record<BadgeVariant, string> = {
  default: 'bg-paper text-muted border border-border',
  candidate: 'bg-secondary-soft text-secondary',
  review: 'bg-warning-soft text-warning',
  approved: 'bg-success-soft text-success',
  rejected: 'bg-danger-soft text-danger',
  registered: 'bg-primary-soft text-primary',
  pending: 'bg-warning-soft text-warning',
  processing: 'bg-secondary-soft text-secondary',
  completed: 'bg-success-soft text-success',
  cancelled: 'bg-danger-soft text-danger',
  success: 'bg-success-soft text-success',
  warning: 'bg-warning-soft text-warning',
  danger: 'bg-danger-soft text-danger',
};

const variantLabels: Partial<Record<BadgeVariant, string>> = {
  candidate: '후보',
  review: '검토중',
  approved: '승인',
  rejected: '거절',
  registered: '등록됨',
  pending: '대기',
  processing: '처리중',
  completed: '완료',
  cancelled: '취소',
};

function resolveVariant(status: string): BadgeVariant {
  const map: Record<string, BadgeVariant> = {
    candidate: 'candidate',
    review: 'review',
    approved: 'approved',
    rejected: 'rejected',
    registered: 'registered',
    pending: 'pending',
    processing: 'processing',
    completed: 'completed',
    cancelled: 'cancelled',
  };
  return map[status.toLowerCase()] ?? 'default';
}

export function Badge({ variant, children, className = '', ...rest }: BadgeProps) {
  const v = variant ?? 'default';
  const label = children ?? variantLabels[v] ?? v;
  return (
    <span
      className={[
        'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium',
        variantClasses[v],
        className,
      ].join(' ')}
      {...rest}
    >
      {label}
    </span>
  );
}

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const v = resolveVariant(status);
  const label = variantLabels[v] ?? status;
  return (
    <Badge variant={v} className={className}>
      {label}
    </Badge>
  );
}
