import { useEffect, useState, useMemo, useCallback, useRef } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useLayoutContext } from '../components/Layout';
import { useApi } from '../hooks/useApi';
import { api } from '../api/client';
import KpiCard from '../components/KpiCard';
import LoadIndicator, { getLoadBgClass } from '../components/LoadIndicator';
import LineChart from '../components/LineChart';
import HeatmapChart from '../components/HeatmapChart';
import { QualityIndicator } from '../components/QualityIndicator';
import type {
  BranchDetail,
  ForecastResponse,
  ForecastGenerationStatus,
  WindowsResponse,
  StaffingResponse,
  HistoryResponse,
} from '../types';

function formatNum(n: number): string {
  return Math.round(n)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

function formatWait(minutes: number): string {
  return minutes.toFixed(1).replace('.', ',') + ' мин';
}

const DAY_NAMES = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];

type TabKey = 'forecast' | 'windows' | 'staffing' | 'history';

export default function BranchPage() {
  const { id } = useParams<{ id: string }>();
  const branchId = Number(id);
  const { dateRange, setPageTitle } = useLayoutContext();
  const [activeTab, setActiveTab] = useState<TabKey>('forecast');

  const { data: branch, loading: branchLoading } = useApi<BranchDetail>(
    () => api.getBranch(branchId),
    [branchId]
  );

  const { data: forecast, loading: forecastLoading, error: forecastError, refetch: refetchForecast } =
    useApi<ForecastResponse>(
      () => api.getForecast(branchId, dateRange.from, dateRange.to),
      [branchId, dateRange.from, dateRange.to]
    );

  useEffect(() => {
    if (branch) {
      setPageTitle(branch.name);
    }
  }, [branch, setPageTitle]);

  if (branchLoading) {
    return <Spinner />;
  }

  if (!branch) {
    return (
      <div className="flex items-center justify-center h-64 text-[#64748B]">
        Филиал не найден.{' '}
        <Link to="/" className="text-[#2563EB] ml-2 underline">
          На главную
        </Link>
      </div>
    );
  }

  const tabs: { key: TabKey; label: string }[] = [
    { key: 'forecast', label: 'Прогноз' },
    { key: 'windows', label: 'Окна' },
    { key: 'staffing', label: 'Штат' },
    { key: 'history', label: 'История' },
  ];

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <nav className="text-sm text-[#64748B]">
        <Link to="/" className="hover:text-[#2563EB]">
          Главная
        </Link>
        <span className="mx-2">&gt;</span>
        <span className="text-[#0F172A]">{branch.name}</span>
      </nav>

      {/* KPI */}
      <div className="grid grid-cols-5 gap-4">
        <KpiCard
          title="Обращений за период (прогноз)"
          value={
            forecast
              ? formatNum(forecast.summary.total_predicted_visits)
              : '-'
          }
        />
        <KpiCard
          title="Среднее ожидание"
          value={formatWait(branch.avg_wait_minutes)}
          color={branch.avg_wait_minutes > 20 ? '#EF4444' : undefined}
        />
        <KpiCard title="Кол-во окон" value={String(branch.num_windows)} />
        <KpiCard
          title="Кол-во сотрудников"
          value={String(branch.num_employees)}
        />
        <KpiCard
          title="Пиковый час"
          value={
            forecast && forecast.summary.peak_hour != null
              ? `${forecast.summary.peak_hour}:00`
              : '-'
          }
          subtitle={
            forecast && forecast.summary.peak_day ? `Пиковый день: ${forecast.summary.peak_day}` : undefined
          }
        />
      </div>

      {/* Tabs */}
      <div className="border-b border-[#E2E8F0]">
        <div className="flex gap-0">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-5 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.key
                  ? 'text-[#2563EB] border-[#2563EB]'
                  : 'text-[#64748B] border-transparent hover:text-[#0F172A]'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      {activeTab === 'forecast' && (
        <ForecastTab
          forecast={forecast}
          loading={forecastLoading}
          error={forecastError}
          refetch={refetchForecast}
          branchId={branchId}
          fromDate={dateRange.from}
          toDate={dateRange.to}
        />
      )}
      {activeTab === 'windows' && (
        <WindowsTab branchId={branchId} fromDate={dateRange.from} toDate={dateRange.to} />
      )}
      {activeTab === 'staffing' && (
        <StaffingTab branchId={branchId} fromDate={dateRange.from} toDate={dateRange.to} />
      )}
      {activeTab === 'history' && <HistoryTab branchId={branchId} />}
    </div>
  );
}

// --- Forecast Tab ---

function ForecastTab({
  forecast,
  loading,
  error,
  refetch,
  branchId,
  fromDate,
  toDate,
}: {
  forecast: ForecastResponse | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
  branchId: number;
  fromDate: string;
  toDate: string;
}) {
  if (loading && !forecast) return <Spinner />;
  if (error) return <ErrorBlock message={error} onRetry={refetch} />;
  if (!forecast || forecast.data.length === 0) {
    return (
      <BranchForecastGenPanel
        branchId={branchId}
        fromDate={fromDate}
        toDate={toDate}
        onComplete={refetch}
      />
    );
  }

  return <ForecastCharts forecast={forecast} />;
}

function ForecastCharts({ forecast }: { forecast: ForecastResponse }) {
  const hasLowQuality = forecast.quality_metrics && forecast.quality_metrics.wMAPE > 25;

  const lineData = useMemo(() => {
    const dailyMap = new Map<string, { value: number; lower: number; upper: number }>();
    for (const p of forecast.data) {
      const existing = dailyMap.get(p.date);
      if (existing) {
        existing.value += p.predicted_visits;
        existing.lower += p.confidence_lower ?? 0;
        existing.upper += p.confidence_upper ?? 0;
      } else {
        dailyMap.set(p.date, {
          value: p.predicted_visits,
          lower: p.confidence_lower ?? 0,
          upper: p.confidence_upper ?? 0,
        });
      }
    }
    return Array.from(dailyMap.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, vals]) => ({
        date,
        value: Math.round(vals.value),
        lower: Math.round(vals.lower),
        upper: Math.round(vals.upper),
      }));
  }, [forecast]);

  const heatmapData = useMemo(() => {
    const heatmapAgg = new Map<string, { total: number; count: number }>();
    for (const p of forecast.data) {
      const d = new Date(p.date);
      const dow = d.getDay();
      const dayIdx = dow === 0 ? 5 : dow - 1;
      if (dow === 0) continue;
      const key = `${dayIdx}-${p.hour}`;
      const existing = heatmapAgg.get(key);
      if (existing) {
        existing.total += p.predicted_visits;
        existing.count += 1;
      } else {
        heatmapAgg.set(key, { total: p.predicted_visits, count: 1 });
      }
    }
    return Array.from(heatmapAgg.entries()).map(([key, vals]) => {
      const [dow, hour] = key.split('-').map(Number);
      return {
        dayOfWeek: dow ?? 0,
        hour: hour ?? 8,
        value: vals.count > 0 ? vals.total / vals.count : 0,
      };
    });
  }, [forecast]);

  return (
    <div className="space-y-6">
      {/* Quality indicator - показываем детальный для low quality */}
      {hasLowQuality ? (
        <QualityIndicator metrics={forecast.quality_metrics} variant="detailed" />
      ) : (
        forecast.quality_metrics && (
          <QualityIndicator metrics={forecast.quality_metrics} variant="inline" />
        )
      )}

      <LineChart
        data={lineData}
        title="Прогноз обращений по дням"
        yAxisLabel="Обращений"
      />
      <HeatmapChart
        data={heatmapData}
        title="Средняя загрузка по часам (день недели)"
      />
    </div>
  );
}

// --- Windows Tab ---

function WindowsTab({
  branchId,
  fromDate,
  toDate,
}: {
  branchId: number;
  fromDate: string;
  toDate: string;
}) {
  const { data, loading, error, refetch } = useApi<WindowsResponse>(
    () => api.getWindows(branchId, fromDate, toDate),
    [branchId, fromDate, toDate]
  );

  if (loading && !data) return <Spinner />;
  if (error) return <ErrorBlock message={error} onRetry={refetch} />;
  if (!data || data.windows.length === 0) {
    return (
      <div className="text-center text-[#64748B] py-12">
        Нет данных по окнам для этого филиала.
      </div>
    );
  }

  const sorted = [...data.windows].sort(
    (a, b) => b.avg_daily_load_percent - a.avg_daily_load_percent
  );

  const statusLabels: Record<string, string> = {
    overloaded: 'Перегружено',
    normal: 'Норма',
    underloaded: 'Низкая',
    idle: 'Простой',
  };

  return (
    <div className="space-y-3">
      {data.data_source === 'forecast' ? (
        <span className="inline-flex items-center rounded-md border border-blue-200 bg-blue-50 px-3 py-1.5 text-sm text-blue-600">
          Прогнозные данные
        </span>
      ) : (
        <span className="inline-flex items-center rounded-md border border-green-200 bg-green-50 px-3 py-1.5 text-sm text-green-600">
          Фактические данные
        </span>
      )}
    <div className="bg-white rounded-lg border border-[#E2E8F0] overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[#E2E8F0] text-[#64748B]">
            <th className="text-left px-4 py-3 font-medium">Окно</th>
            <th className="text-right px-4 py-3 font-medium">
              Ср. обращ./день
            </th>
            <th className="text-right px-4 py-3 font-medium">
              Ср. загрузка
            </th>
            <th className="text-center px-4 py-3 font-medium">Статус</th>
            {/* Hourly breakdown */}
            {Array.from({ length: 12 }, (_, i) => (
              <th
                key={i}
                className="text-center px-2 py-3 font-medium text-xs"
              >
                {(8 + i).toString().padStart(2, '0')}:00
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((w) => (
            <tr
              key={w.window_number}
              className="border-b border-[#F1F5F9] hover:bg-[#F8FAFC]"
            >
              <td className="px-4 py-2.5 text-[#0F172A] font-medium">
                Окно {w.window_number}
              </td>
              <td className="text-right px-4 py-2.5 text-[#0F172A]">
                {w.load_by_hour.length > 0
                  ? (
                      w.load_by_hour.reduce((s, h) => s + h.avg_visits, 0) /
                      w.load_by_hour.length
                    )
                      .toFixed(1)
                      .replace('.', ',')
                  : '-'}
              </td>
              <td className="text-right px-4 py-2.5">
                <span className="flex items-center justify-end gap-2">
                  <LoadIndicator value={w.avg_daily_load_percent} size="sm" />
                  <span className="text-[#0F172A]">
                    {w.avg_daily_load_percent.toFixed(1).replace('.', ',')}%
                  </span>
                </span>
              </td>
              <td className="text-center px-4 py-2.5">
                <span
                  className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${getLoadBgClass(
                    w.avg_daily_load_percent
                  )}`}
                >
                  {statusLabels[w.status] ?? w.status}
                </span>
              </td>
              {Array.from({ length: 12 }, (_, i) => {
                const hourData = w.load_by_hour.find(
                  (h) => h.hour === 8 + i
                );
                const loadPct = hourData?.load_percent ?? 0;
                return (
                  <td
                    key={i}
                    className="text-center px-2 py-2.5 text-xs"
                    style={{
                      backgroundColor:
                        loadPct > 85
                          ? 'rgba(239,68,68,0.2)'
                          : loadPct > 70
                            ? 'rgba(249,115,22,0.2)'
                            : loadPct > 50
                              ? 'rgba(34,197,94,0.15)'
                              : loadPct > 20
                                ? 'rgba(59,130,246,0.1)'
                                : 'transparent',
                    }}
                  >
                    {hourData
                      ? loadPct.toFixed(0) + '%'
                      : '-'}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {/* Legend */}
      <div className="flex items-center gap-4 px-4 py-3 text-xs text-[#64748B] border-t border-[#E2E8F0]">
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded bg-[#EF4444]" /> &gt;85% Критическая
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded bg-[#F97316]" /> 70-85% Высокая
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded bg-[#22C55E]" /> 50-70% Нормальная
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded bg-[#3B82F6]" /> 20-50% Низкая
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded bg-[#9CA3AF]" /> &lt;20% Простой
        </span>
      </div>
    </div>
    </div>
  );
}

// --- Staffing Tab ---

function StaffingTab({
  branchId,
  fromDate,
  toDate,
}: {
  branchId: number;
  fromDate: string;
  toDate: string;
}) {
  const { data, loading, error, refetch } = useApi<StaffingResponse>(
    () => api.getStaffing(branchId, fromDate, toDate),
    [branchId, fromDate, toDate]
  );

  if (loading && !data) return <Spinner />;
  if (error) return <ErrorBlock message={error} onRetry={refetch} />;
  if (!data || data.recommendations.length === 0) {
    return (
      <div className="text-center text-[#64748B] py-12">
        Нет данных по штатному расписанию. Сначала сгенерируйте прогноз.
      </div>
    );
  }

  // Group by date
  const dateMap = new Map<
    string,
    Map<number, (typeof data.recommendations)[number]>
  >();
  for (const rec of data.recommendations) {
    let hourMap = dateMap.get(rec.date);
    if (!hourMap) {
      hourMap = new Map();
      dateMap.set(rec.date, hourMap);
    }
    hourMap.set(rec.hour, rec);
  }

  const dates = Array.from(dateMap.keys()).sort();
  const hours = Array.from({ length: 12 }, (_, i) => 8 + i);

  // Summary
  const totalRecs = data.recommendations;
  const avgRequired =
    totalRecs.length > 0
      ? totalRecs.reduce((s, r) => s + r.required_windows, 0) / totalRecs.length
      : 0;
  const avgCurrent =
    totalRecs.length > 0
      ? totalRecs.reduce((s, r) => s + r.current_windows_avg, 0) /
        totalRecs.length
      : 0;
  const deficitHours = totalRecs.filter((r) => r.delta > 0).length;

  function getCellColor(delta: number): string {
    if (delta >= 2) return 'rgba(239,68,68,0.25)';
    if (delta === 1) return 'rgba(249,115,22,0.2)';
    if (delta <= -2) return 'rgba(156,163,175,0.2)';
    return 'rgba(34,197,94,0.15)';
  }

  function formatDate(dateStr: string): string {
    const d = new Date(dateStr);
    const dd = d.getDate().toString().padStart(2, '0');
    const mm = (d.getMonth() + 1).toString().padStart(2, '0');
    const dayName = DAY_NAMES[d.getDay()] ?? '';
    return `${dd}.${mm} ${dayName}`;
  }

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="grid grid-cols-3 gap-4">
        <KpiCard
          title="Рекомендуемое ср. кол-во окон"
          value={avgRequired.toFixed(1).replace('.', ',')}
          subtitle={`Текущее: ${avgCurrent.toFixed(1).replace('.', ',')}`}
        />
        <KpiCard
          title="Часов с дефицитом"
          value={String(deficitHours)}
          subtitle={`из ${totalRecs.length}`}
          color={deficitHours > totalRecs.length / 2 ? '#EF4444' : undefined}
        />
        <KpiCard
          title="Средний дефицит"
          value={
            totalRecs.length > 0
              ? (
                  totalRecs.reduce((s, r) => s + Math.max(0, r.delta), 0) /
                  totalRecs.length
                )
                  .toFixed(1)
                  .replace('.', ',')
              : '0'
          }
          subtitle="окон/час"
        />
      </div>

      {/* Matrix */}
      <div className="bg-white rounded-lg border border-[#E2E8F0] overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#E2E8F0] text-[#64748B]">
              <th className="text-left px-3 py-2 font-medium sticky left-0 bg-white z-10">
                Дата
              </th>
              {hours.map((h) => (
                <th key={h} className="text-center px-2 py-2 font-medium text-xs">
                  {h.toString().padStart(2, '0')}:00
                </th>
              ))}
              <th className="text-center px-3 py-2 font-medium text-xs">
                Макс
              </th>
            </tr>
          </thead>
          <tbody>
            {dates.map((date) => {
              const hourMap = dateMap.get(date);
              const maxRequired = Math.max(
                ...hours.map((h) => hourMap?.get(h)?.required_windows ?? 0)
              );

              return (
                <tr
                  key={date}
                  className="border-b border-[#F1F5F9]"
                >
                  <td className="px-3 py-2 text-[#0F172A] font-medium text-xs whitespace-nowrap sticky left-0 bg-white z-10">
                    {formatDate(date)}
                  </td>
                  {hours.map((h) => {
                    const rec = hourMap?.get(h);
                    const delta = rec?.delta ?? 0;
                    return (
                      <td
                        key={h}
                        className="text-center px-2 py-2 text-xs"
                        style={{ backgroundColor: getCellColor(delta) }}
                        title={`Требуется: ${rec?.required_windows ?? '-'}, Текущее: ${rec?.current_windows_avg ?? '-'}, Дельта: ${delta}`}
                      >
                        {rec?.required_windows ?? '-'}
                      </td>
                    );
                  })}
                  <td className="text-center px-3 py-2 text-xs font-semibold text-[#0F172A]">
                    {maxRequired}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {/* Legend */}
        <div className="flex items-center gap-4 px-4 py-3 text-xs text-[#64748B] border-t border-[#E2E8F0]">
          <span className="flex items-center gap-1">
            <span
              className="w-3 h-3 rounded"
              style={{ backgroundColor: 'rgba(239,68,68,0.25)' }}
            />{' '}
            Дефицит 2+
          </span>
          <span className="flex items-center gap-1">
            <span
              className="w-3 h-3 rounded"
              style={{ backgroundColor: 'rgba(249,115,22,0.2)' }}
            />{' '}
            Дефицит 1
          </span>
          <span className="flex items-center gap-1">
            <span
              className="w-3 h-3 rounded"
              style={{ backgroundColor: 'rgba(34,197,94,0.15)' }}
            />{' '}
            Норма
          </span>
          <span className="flex items-center gap-1">
            <span
              className="w-3 h-3 rounded"
              style={{ backgroundColor: 'rgba(156,163,175,0.2)' }}
            />{' '}
            Избыток 2+
          </span>
        </div>
      </div>
    </div>
  );
}

// --- History Tab ---

function HistoryTab({ branchId }: { branchId: number }) {
  const [fromMonth, setFromMonth] = useState('2023-01');
  const [toMonth, setToMonth] = useState('2024-02');

  const { data, loading, error, refetch } = useApi<HistoryResponse>(
    () => api.getHistory(branchId, fromMonth, toMonth),
    [branchId, fromMonth, toMonth]
  );

  const lineData = useMemo(() => {
    if (!data?.daily) return [];
    return data.daily.map((d) => ({
      date: d.date,
      value: d.total_visits,
      lower: Math.round(d.total_visits * 0.85),
      upper: Math.round(d.total_visits * 1.15),
    }));
  }, [data]);

  const heatmapData = useMemo(() => {
    if (!data?.hourly) return [];
    const agg = new Map<string, { total: number; count: number }>();
    for (const h of data.hourly) {
      const d = new Date(h.date);
      const dow = d.getDay();
      const dayIdx = dow === 0 ? 5 : dow - 1;
      if (dow === 0) continue;
      const key = `${dayIdx}-${h.hour}`;
      const existing = agg.get(key);
      if (existing) {
        existing.total += h.total_visits;
        existing.count += 1;
      } else {
        agg.set(key, { total: h.total_visits, count: 1 });
      }
    }
    return Array.from(agg.entries()).map(([key, vals]) => {
      const [dow, hour] = key.split('-').map(Number);
      return {
        dayOfWeek: dow ?? 0,
        hour: hour ?? 8,
        value: vals.count > 0 ? vals.total / vals.count : 0,
      };
    });
  }, [data]);

  return (
    <div className="space-y-6">
      {/* Period selector */}
      <div className="flex items-center gap-3 text-sm">
        <label className="text-[#64748B]">Период:</label>
        <input
          type="month"
          value={fromMonth}
          onChange={(e) => setFromMonth(e.target.value)}
          className="px-3 py-1.5 border border-[#E2E8F0] rounded text-sm focus:outline-none focus:border-[#2563EB]"
        />
        <span className="text-[#64748B]">--</span>
        <input
          type="month"
          value={toMonth}
          onChange={(e) => setToMonth(e.target.value)}
          className="px-3 py-1.5 border border-[#E2E8F0] rounded text-sm focus:outline-none focus:border-[#2563EB]"
        />
      </div>

      {loading && <Spinner />}
      {error && <ErrorBlock message={error} onRetry={refetch} />}
      {!loading && !error && data && (
        <>
          <LineChart
            data={lineData}
            title="Исторические обращения по дням"
            yAxisLabel="Обращений"
          />
          <HeatmapChart
            data={heatmapData}
            title="Фактическая загрузка по часам"
          />
        </>
      )}
      {!loading && !error && (!data || data.daily.length === 0) && (
        <div className="text-center text-[#64748B] py-12">
          Нет исторических данных за выбранный период.
        </div>
      )}
    </div>
  );
}

// --- Shared helpers ---

function Spinner() {
  return (
    <div className="flex items-center justify-center h-48">
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 border-3 border-[#2563EB] border-t-transparent rounded-full animate-spin" />
        <span className="text-sm text-[#64748B]">Загрузка данных...</span>
      </div>
    </div>
  );
}

function ErrorBlock({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="flex items-center justify-center h-48">
      <div className="text-center">
        <p className="text-[#EF4444] mb-3">{message}</p>
        <button
          onClick={onRetry}
          className="px-4 py-2 bg-[#2563EB] text-white rounded text-sm hover:bg-[#1D4ED8]"
        >
          Повторить
        </button>
      </div>
    </div>
  );
}

function BranchForecastGenPanel({
  branchId,
  fromDate,
  toDate,
  onComplete,
}: {
  branchId: number;
  fromDate: string;
  toDate: string;
  onComplete: () => void;
}) {
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [genStatus, setGenStatus] = useState<ForecastGenerationStatus | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  useEffect(() => {
    return stopPolling;
  }, [stopPolling]);

  const handleGenerate = async () => {
    setStarting(true);
    setError(null);
    try {
      await api.generateForecast({
        from_date: fromDate,
        to_date: toDate,
        branch_id: branchId,
      });
      setGenStatus({
        status: 'running',
        progress: 0,
        total_branches: 1,
        current_branch_name: null,
        started_at: new Date().toISOString(),
        error_message: null,
      });
      intervalRef.current = setInterval(async () => {
        try {
          const s = await api.getForecastGenerationStatus();
          setGenStatus(s);
          if (s.status === 'completed' || s.status === 'error') {
            stopPolling();
            if (s.status === 'completed') {
              onComplete();
            }
          }
        } catch {
          // ignore
        }
      }, 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка запуска генерации');
    } finally {
      setStarting(false);
    }
  };

  const isRunning = genStatus?.status === 'running';
  const hasError = genStatus?.status === 'error';

  return (
    <div className="flex items-center justify-center h-48">
      <div className="text-center">
        {!genStatus || genStatus.status === 'idle' ? (
          <>
            <p className="text-lg mb-2 text-[#64748B]">Прогноз не сгенерирован</p>
            <p className="text-sm text-[#64748B] mb-4">
              Нажмите кнопку для генерации прогноза этого филиала
            </p>
            <button
              onClick={handleGenerate}
              disabled={starting}
              className="px-5 py-2.5 bg-[#2563EB] text-white rounded-lg text-sm font-medium hover:bg-[#1D4ED8] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {starting ? 'Запуск...' : 'Сгенерировать прогноз'}
            </button>
            {error && <p className="text-[#EF4444] text-sm mt-3">{error}</p>}
          </>
        ) : isRunning ? (
          <>
            <div className="w-8 h-8 border-3 border-[#2563EB] border-t-transparent rounded-full animate-spin mx-auto mb-3" />
            <p className="text-sm font-medium text-[#0F172A]">
              Генерация прогноза...
            </p>
          </>
        ) : hasError ? (
          <>
            <p className="text-[#EF4444] mb-3">{genStatus.error_message}</p>
            <button
              onClick={handleGenerate}
              className="px-5 py-2.5 bg-[#2563EB] text-white rounded-lg text-sm font-medium hover:bg-[#1D4ED8]"
            >
              Повторить
            </button>
          </>
        ) : null}
      </div>
    </div>
  );
}
