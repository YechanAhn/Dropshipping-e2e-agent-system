import { ReactNode } from 'react';

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center px-6">
      {icon && (
        <div className="w-14 h-14 rounded-2xl bg-paper flex items-center justify-center text-muted mb-5 border border-border">
          {icon}
        </div>
      )}
      <p className="text-base font-semibold text-ink mb-1">{title}</p>
      {description && (
        <p className="text-sm text-muted max-w-sm">{description}</p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
