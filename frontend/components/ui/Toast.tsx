'use client';

import { createContext, useCallback, useContext, useReducer, ReactNode } from 'react';
import { CheckCircle, XCircle, AlertTriangle, Info, X } from 'lucide-react';

type ToastVariant = 'success' | 'error' | 'warning' | 'info';

interface Toast {
  id: string;
  variant: ToastVariant;
  title: string;
  message?: string;
}

interface ToastContextValue {
  toast: (opts: Omit<Toast, 'id'>) => void;
  success: (title: string, message?: string) => void;
  error: (title: string, message?: string) => void;
  warning: (title: string, message?: string) => void;
  info: (title: string, message?: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

type Action =
  | { type: 'ADD'; toast: Toast }
  | { type: 'REMOVE'; id: string };

function reducer(state: Toast[], action: Action): Toast[] {
  switch (action.type) {
    case 'ADD':
      return [...state, action.toast];
    case 'REMOVE':
      return state.filter((t) => t.id !== action.id);
    default:
      return state;
  }
}

const iconMap: Record<ToastVariant, ReactNode> = {
  success: <CheckCircle size={16} />,
  error: <XCircle size={16} />,
  warning: <AlertTriangle size={16} />,
  info: <Info size={16} />,
};

const styleMap: Record<ToastVariant, string> = {
  success: 'border-success/30 bg-success-soft text-success',
  error: 'border-danger/30 bg-danger-soft text-danger',
  warning: 'border-warning/30 bg-warning-soft text-warning',
  info: 'border-secondary/30 bg-secondary-soft text-secondary',
};

const textMap: Record<ToastVariant, string> = {
  success: 'text-success',
  error: 'text-danger',
  warning: 'text-warning',
  info: 'text-secondary',
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, dispatch] = useReducer(reducer, []);

  const dismiss = useCallback((id: string) => {
    dispatch({ type: 'REMOVE', id });
  }, []);

  const addToast = useCallback((opts: Omit<Toast, 'id'>) => {
    const id = Math.random().toString(36).slice(2);
    dispatch({ type: 'ADD', toast: { ...opts, id } });
    setTimeout(() => dispatch({ type: 'REMOVE', id }), 4000);
  }, []);

  const value: ToastContextValue = {
    toast: addToast,
    success: (title, message) => addToast({ variant: 'success', title, message }),
    error: (title, message) => addToast({ variant: 'error', title, message }),
    warning: (title, message) => addToast({ variant: 'warning', title, message }),
    info: (title, message) => addToast({ variant: 'info', title, message }),
  };

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        aria-label="알림"
        className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role="alert"
            className={[
              'pointer-events-auto flex items-start gap-3 rounded-2xl border p-4 shadow-elevated',
              'animate-in slide-in-from-bottom-2 duration-200',
              styleMap[t.variant],
            ].join(' ')}
          >
            <span className="flex-shrink-0 mt-0.5">{iconMap[t.variant]}</span>
            <div className="flex-1 min-w-0">
              <p className={['text-sm font-semibold', textMap[t.variant]].join(' ')}>{t.title}</p>
              {t.message && (
                <p className="text-xs mt-0.5 opacity-80">{t.message}</p>
              )}
            </div>
            <button
              onClick={() => dismiss(t.id)}
              className="flex-shrink-0 opacity-60 hover:opacity-100 transition-opacity"
              aria-label="닫기"
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}
