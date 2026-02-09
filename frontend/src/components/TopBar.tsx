interface TopBarProps {
  title: string;
  selectedMonth: string;
  onMonthChange: (month: string) => void;
}

function getAvailableMonths(): { value: string; label: string }[] {
  const months: { value: string; label: string }[] = [];
  const monthNames = [
    'Январь', 'Февраль', 'Март', 'Апрель',
    'Май', 'Июнь', 'Июль', 'Август',
    'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
  ];
  const now = new Date();

  for (let offset = -6; offset <= 3; offset++) {
    const d = new Date(now.getFullYear(), now.getMonth() + offset, 1);
    const y = d.getFullYear();
    const m = d.getMonth();
    const value = `${y}-${String(m + 1).padStart(2, '0')}`;
    const name = monthNames[m];
    months.push({ value, label: `${name ?? ''} ${y}` });
  }

  return months;
}

export default function TopBar({
  title,
  selectedMonth,
  onMonthChange,
}: TopBarProps) {
  const months = getAvailableMonths();

  return (
    <header className="h-14 bg-white border-b border-[#E2E8F0] flex items-center justify-between px-6 shrink-0">
      <h1 className="text-lg font-semibold text-[#0F172A] truncate">
        {title}
      </h1>
      <div className="flex items-center gap-3">
        <label className="text-sm text-[#64748B]" htmlFor="month-picker">
          Период:
        </label>
        <select
          id="month-picker"
          value={selectedMonth}
          onChange={(e) => onMonthChange(e.target.value)}
          className="px-3 py-1.5 border border-[#E2E8F0] rounded text-sm text-[#0F172A] bg-white focus:outline-none focus:border-[#2563EB] cursor-pointer"
        >
          {months.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
      </div>
    </header>
  );
}
