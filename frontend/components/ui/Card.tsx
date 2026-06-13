import { HTMLAttributes } from 'react';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  elevated?: boolean;
}

export function Card({ elevated, className = '', children, ...rest }: CardProps) {
  return (
    <div
      className={[
        'bg-surface rounded-2xl border border-border transition-shadow duration-200',
        elevated ? 'shadow-elevated' : 'shadow-card',
        className,
      ].join(' ')}
      {...rest}
    >
      {children}
    </div>
  );
}
