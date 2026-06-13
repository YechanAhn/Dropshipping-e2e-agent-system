'use client';

interface SliderProps {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  label?: string;
  disabled?: boolean;
}

export function Slider({ value, onChange, min = 0, max = 1, step = 0.01, label, disabled }: SliderProps) {
  const pct = ((value - min) / (max - min)) * 100;

  return (
    <div className="flex items-center gap-4">
      {label && (
        <span className="text-sm text-ink font-medium w-24 flex-shrink-0">{label}</span>
      )}
      <div className="flex-1 relative">
        <div className="h-2 bg-border rounded-full overflow-hidden">
          <div
            className="h-full bg-primary rounded-full transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          className="absolute inset-0 w-full opacity-0 cursor-pointer h-2 disabled:cursor-not-allowed"
          aria-label={label}
        />
      </div>
      <span className="text-sm font-mono text-ink w-12 text-right flex-shrink-0">
        {value.toFixed(2)}
      </span>
    </div>
  );
}
