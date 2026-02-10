import type { DateRange } from './Layout';

interface TopBarProps {
  title: string;
  dateRange: DateRange;
  onDateRangeChange: (range: DateRange) => void;
}

function formatDateISO(d: Date): string {
  const y = d.getFullYear();
  const m = (d.getMonth() + 1).toString().padStart(2, '0');
  const day = d.getDate().toString().padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function formatDateRU(isoDate: string): string {
  const [y, m, d] = isoDate.split('-');
  return `${d}.${m}.${y}`;
}

function daysBetween(from: string, to: string): number {
  const a = new Date(from);
  const b = new Date(to);
  return Math.round((b.getTime() - a.getTime()) / (1000 * 60 * 60 * 24));
}

function getMinDate(): string {
  const d = new Date();
  d.setMonth(d.getMonth() - 6);
  return formatDateISO(d);
}

function getMaxDate(): string {
  const d = new Date();
  d.setMonth(d.getMonth() + 3);
  return formatDateISO(d);
}

export default function TopBar({
  title,
  dateRange,
  onDateRangeChange,
}: TopBarProps) {
  const days = daysBetween(dateRange.from, dateRange.to);

  const handleFromChange = (newFrom: string) => {
    const fromDate = new Date(newFrom);
    const toDate = new Date(fromDate);
    toDate.setDate(toDate.getDate() + 30);
    onDateRangeChange({
      from: newFrom,
      to: formatDateISO(toDate),
    });
  };

  return (
    <header className="h-14 bg-white border-b border-[#E2E8F0] flex items-center justify-between px-6 shrink-0">
      <h1 className="text-lg font-semibold text-[#0F172A] truncate">
        {title}
      </h1>
      <div className="flex items-center gap-3">
        <label className="text-sm text-[#64748B]" htmlFor="date-from-picker">
          Период:
        </label>
        <input
          id="date-from-picker"
          type="date"
          value={dateRange.from}
          min={getMinDate()}
          max={getMaxDate()}
          onChange={(e) => handleFromChange(e.target.value)}
          className="px-3 py-1.5 border border-[#E2E8F0] rounded text-sm text-[#0F172A] bg-white focus:outline-none focus:border-[#2563EB] cursor-pointer"
        />
        <span className="text-sm text-[#64748B]">
          {formatDateRU(dateRange.from)} — {formatDateRU(dateRange.to)} ({days} дней)
        </span>
      </div>
    </header>
  );
}
