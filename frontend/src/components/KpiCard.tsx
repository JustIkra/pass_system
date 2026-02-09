interface KpiCardProps {
  title: string;
  value: string;
  subtitle?: string;
  color?: string;
  icon?: React.ReactNode;
}

export default function KpiCard({
  title,
  value,
  subtitle,
  color,
  icon,
}: KpiCardProps) {
  return (
    <div className="bg-white rounded-lg shadow-sm border border-[#E2E8F0] p-5 min-h-[96px] flex flex-col justify-between">
      <div className="flex items-center justify-between">
        <span className="text-sm text-[#64748B] font-medium">{title}</span>
        {icon && <span className="text-[#64748B]">{icon}</span>}
      </div>
      <div className="mt-2">
        <span
          className="text-2xl font-bold"
          style={{ color: color ?? '#0F172A' }}
        >
          {value}
        </span>
        {subtitle && (
          <p className="text-xs text-[#64748B] mt-1">{subtitle}</p>
        )}
      </div>
    </div>
  );
}
