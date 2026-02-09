import type { LoadLevel } from '../types';

interface LoadIndicatorProps {
  value: number;
  showLabel?: boolean;
  size?: 'sm' | 'md';
}

interface LoadConfig {
  color: string;
  label: string;
  level: LoadLevel;
}

export function getLoadConfig(value: number): LoadConfig {
  if (value > 85)
    return { color: '#EF4444', label: 'Критическая', level: 'critical' };
  if (value > 70)
    return { color: '#F97316', label: 'Высокая', level: 'high' };
  if (value > 50)
    return { color: '#22C55E', label: 'Нормальная', level: 'normal' };
  if (value > 20)
    return { color: '#3B82F6', label: 'Низкая', level: 'low' };
  return { color: '#9CA3AF', label: 'Простой', level: 'idle' };
}

export function getLoadBgClass(value: number): string {
  if (value > 85) return 'bg-[#EF4444] text-white';
  if (value > 70) return 'bg-[#F97316] text-white';
  if (value > 50) return 'bg-[#22C55E] text-white';
  if (value > 20) return 'bg-[#3B82F6] text-white';
  return 'bg-[#9CA3AF] text-white';
}

export default function LoadIndicator({
  value,
  showLabel = false,
  size = 'md',
}: LoadIndicatorProps) {
  const config = getLoadConfig(value);
  const dotSize = size === 'sm' ? 'w-2.5 h-2.5' : 'w-3 h-3';

  return (
    <span className="inline-flex items-center gap-2">
      <span
        className={`${dotSize} rounded-full inline-block shrink-0`}
        style={{ backgroundColor: config.color }}
      />
      {showLabel && (
        <span
          className="text-sm font-medium"
          style={{ color: config.color }}
        >
          {config.label}
        </span>
      )}
    </span>
  );
}
