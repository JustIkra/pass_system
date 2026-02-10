import { useEffect, useState, useMemo, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLayoutContext } from '../components/Layout';
import { useApi } from '../hooks/useApi';
import { api } from '../api/client';
import KpiCard from '../components/KpiCard';
import LoadIndicator from '../components/LoadIndicator';
import type { OverviewResponse, Branch, ForecastGenerationStatus } from '../types';

function formatNum(n: number): string {
  return Math.round(n)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

function formatWait(minutes: number): string {
  return minutes.toFixed(1).replace('.', ',') + ' мин';
}

export default function OverviewPage() {
  const { dateRange, setPageTitle } = useLayoutContext();
  const navigate = useNavigate();

  useEffect(() => {
    setPageTitle('Обзор сети МФЦ');
  }, [setPageTitle]);

  const {
    data,
    loading,
    error,
    refetch,
  } = useApi<OverviewResponse>(
    () => api.getOverview(dateRange.from, dateRange.to),
    [dateRange.from, dateRange.to]
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-3 border-[#2563EB] border-t-transparent rounded-full animate-spin" />
          <span className="text-sm text-[#64748B]">Загрузка данных...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <p className="text-[#EF4444] mb-3">{error}</p>
          <button
            onClick={refetch}
            className="px-4 py-2 bg-[#2563EB] text-white rounded text-sm hover:bg-[#1D4ED8]"
          >
            Повторить
          </button>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <ForecastGenerationPanel
        fromDate={dateRange.from}
        toDate={dateRange.to}
        onComplete={refetch}
      />
    );
  }

  const overloadedCount = data.top_overloaded.length;
  const underloadedCount = data.top_underloaded.length;

  return (
    <div className="space-y-6">
      {/* Regenerate button */}
      <div className="flex justify-end">
        <RegenerateButton
          fromDate={dateRange.from}
          toDate={dateRange.to}
          onComplete={refetch}
        />
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-4">
        <KpiCard
          title="Всего обращений (прогноз)"
          value={formatNum(data.total_predicted_visits)}
          subtitle={`${data.total_branches} филиалов`}
        />
        <KpiCard
          title="Среднее время ожидания"
          value={formatWait(data.avg_predicted_wait)}
          color={data.avg_predicted_wait > 20 ? '#EF4444' : undefined}
        />
        <KpiCard
          title="Перегруженных филиалов"
          value={String(overloadedCount)}
          color={overloadedCount > 0 ? '#EF4444' : '#22C55E'}
          subtitle="ожидание > 20 мин"
        />
        <KpiCard
          title="Простаивающих филиалов"
          value={String(underloadedCount)}
          color={underloadedCount > 5 ? '#F97316' : '#3B82F6'}
          subtitle="загрузка < 30%"
        />
      </div>

      {/* Top tables */}
      <div className="grid grid-cols-2 gap-4">
        {/* Overloaded */}
        <div className="bg-white rounded-lg shadow-sm border border-[#E2E8F0]">
          <div className="px-4 py-3 border-b border-[#E2E8F0]">
            <h2 className="text-sm font-semibold text-[#0F172A]">
              Самые загруженные филиалы
            </h2>
          </div>
          {data.top_overloaded.length === 0 ? (
            <div className="px-4 py-6 text-sm text-[#64748B] text-center">
              Нет данных для отображения
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#E2E8F0] text-[#64748B]">
                  <th className="text-left px-4 py-2 font-medium">Филиал</th>
                  <th className="text-right px-4 py-2 font-medium">Ожидание</th>
                  <th className="text-center px-4 py-2 font-medium">Статус</th>
                </tr>
              </thead>
              <tbody>
                {data.top_overloaded.map((b) => (
                  <tr
                    key={b.branch_id}
                    className="border-b border-[#F1F5F9] hover:bg-[#F8FAFC] cursor-pointer"
                    onClick={() => navigate(`/branches/${b.branch_id}`)}
                  >
                    <td className="px-4 py-2.5 text-[#0F172A]">
                      {b.branch_name}
                    </td>
                    <td className="text-right px-4 py-2.5 text-[#0F172A]">
                      {formatWait(b.predicted_avg_wait)}
                    </td>
                    <td className="text-center px-4 py-2.5">
                      <LoadIndicator value={Math.min(100, Math.round(b.predicted_avg_wait / 20 * 100))} showLabel />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Underloaded */}
        <div className="bg-white rounded-lg shadow-sm border border-[#E2E8F0]">
          <div className="px-4 py-3 border-b border-[#E2E8F0]">
            <h2 className="text-sm font-semibold text-[#0F172A]">
              Самые недогруженные филиалы
            </h2>
          </div>
          {data.top_underloaded.length === 0 ? (
            <div className="px-4 py-6 text-sm text-[#64748B] text-center">
              Нет данных для отображения
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#E2E8F0] text-[#64748B]">
                  <th className="text-left px-4 py-2 font-medium">Филиал</th>
                  <th className="text-right px-4 py-2 font-medium">Загрузка</th>
                  <th className="text-center px-4 py-2 font-medium">Статус</th>
                </tr>
              </thead>
              <tbody>
                {data.top_underloaded.map((b) => (
                  <tr
                    key={b.branch_id}
                    className="border-b border-[#F1F5F9] hover:bg-[#F8FAFC] cursor-pointer"
                    onClick={() => navigate(`/branches/${b.branch_id}`)}
                  >
                    <td className="px-4 py-2.5 text-[#0F172A]">
                      {b.branch_name}
                    </td>
                    <td className="text-right px-4 py-2.5 text-[#0F172A]">
                      {b.avg_load_percent.toFixed(1).replace('.', ',')}%
                    </td>
                    <td className="text-center px-4 py-2.5">
                      <LoadIndicator value={b.avg_load_percent} showLabel />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Full branches table */}
      <div className="bg-white rounded-lg shadow-sm border border-[#E2E8F0]">
        <div className="px-4 py-3 border-b border-[#E2E8F0]">
          <h2 className="text-sm font-semibold text-[#0F172A]">Все филиалы</h2>
        </div>
        <AllBranchesTable onRowClick={(id) => navigate(`/branches/${id}`)} />
      </div>
    </div>
  );
}

function AllBranchesTable({
  onRowClick,
}: {
  onRowClick: (id: number) => void;
}) {
  const { data: branches, loading } = useApi<Branch[]>(
    () => api.getBranches(),
    []
  );
  const [search, setSearch] = useState('');
  const [sortField, setSortField] = useState<'name' | 'total_records'>('name');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');

  const filtered = useMemo(() => {
    if (!branches) return [];
    let result = [...branches];
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter((b) => b.name.toLowerCase().includes(q));
    }
    result.sort((a, b) => {
      let cmp = 0;
      if (sortField === 'name') {
        cmp = a.name.localeCompare(b.name, 'ru');
      } else {
        cmp = a.total_records - b.total_records;
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return result;
  }, [branches, search, sortField, sortDir]);

  const toggleSort = (field: 'name' | 'total_records') => {
    if (sortField === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDir('asc');
    }
  };

  if (loading) {
    return (
      <div className="px-4 py-8 text-center text-sm text-[#64748B]">
        Загрузка списка филиалов...
      </div>
    );
  }

  return (
    <div>
      <div className="px-4 py-3">
        <input
          type="text"
          placeholder="Поиск по названию..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full max-w-sm px-3 py-2 border border-[#E2E8F0] rounded text-sm focus:outline-none focus:border-[#2563EB]"
        />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#E2E8F0] text-[#64748B]">
              <th
                className="text-left px-4 py-2 font-medium cursor-pointer hover:text-[#0F172A] select-none"
                onClick={() => toggleSort('name')}
              >
                Название{' '}
                {sortField === 'name' &&
                  (sortDir === 'asc' ? '\u2191' : '\u2193')}
              </th>
              <th className="text-left px-4 py-2 font-medium">МФЦ</th>
              <th
                className="text-right px-4 py-2 font-medium cursor-pointer hover:text-[#0F172A] select-none"
                onClick={() => toggleSort('total_records')}
                title="Общее количество обращений за весь период наблюдений"
              >
                Обращений (всего){' '}
                {sortField === 'total_records' &&
                  (sortDir === 'asc' ? '\u2191' : '\u2193')}
              </th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((b) => (
              <tr
                key={b.id}
                className="border-b border-[#F1F5F9] hover:bg-[#F8FAFC] cursor-pointer transition-colors"
                onClick={() => onRowClick(b.id)}
              >
                <td className="px-4 py-2.5 text-[#0F172A] font-medium">
                  {b.name}
                </td>
                <td className="px-4 py-2.5 text-[#64748B] text-xs truncate max-w-[200px]">
                  {b.depart_name_mfc ?? '-'}
                </td>
                <td className="text-right px-4 py-2.5 text-[#0F172A]">
                  {formatNum(b.total_records)}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td
                  colSpan={3}
                  className="px-4 py-6 text-center text-[#64748B]"
                >
                  Нет данных для отображения
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// --- Forecast generation components ---

function useGenerationPoller(onComplete: () => void) {
  const [genStatus, setGenStatus] = useState<ForecastGenerationStatus | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling();
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
        // ignore polling errors
      }
    }, 2000);
  }, [stopPolling, onComplete]);

  useEffect(() => {
    return stopPolling;
  }, [stopPolling]);

  return { genStatus, startPolling, stopPolling, setGenStatus };
}

function ForecastGenerationPanel({
  fromDate,
  toDate,
  branchId,
  onComplete,
}: {
  fromDate: string;
  toDate: string;
  branchId?: number;
  onComplete: () => void;
}) {
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { genStatus, startPolling, setGenStatus } = useGenerationPoller(onComplete);

  const handleGenerate = async () => {
    setStarting(true);
    setError(null);
    try {
      await api.generateForecast({
        from_date: fromDate,
        to_date: toDate,
        branch_id: branchId ?? null,
      });
      setGenStatus({
        status: 'running',
        progress: 0,
        total_branches: 0,
        current_branch_name: null,
        started_at: new Date().toISOString(),
        error_message: null,
      });
      startPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка запуска генерации');
    } finally {
      setStarting(false);
    }
  };

  const isRunning = genStatus?.status === 'running';
  const isCompleted = genStatus?.status === 'completed';
  const hasError = genStatus?.status === 'error';

  return (
    <div className="flex items-center justify-center h-64">
      <div className="text-center">
        {!genStatus || genStatus.status === 'idle' ? (
          <>
            <p className="text-lg mb-2 text-[#64748B]">Прогноз не сгенерирован</p>
            <p className="text-sm text-[#64748B] mb-4">
              Нажмите кнопку для генерации прогноза на выбранный период
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
            <p className="text-sm font-medium text-[#0F172A] mb-1">
              Генерация прогноза...
            </p>
            {genStatus.total_branches > 0 && (
              <>
                <div className="w-64 h-2 bg-[#E2E8F0] rounded-full mx-auto mb-2">
                  <div
                    className="h-2 bg-[#2563EB] rounded-full transition-all"
                    style={{
                      width: `${Math.round((genStatus.progress / genStatus.total_branches) * 100)}%`,
                    }}
                  />
                </div>
                <p className="text-xs text-[#64748B]">
                  {genStatus.progress}/{genStatus.total_branches} филиалов
                  {genStatus.current_branch_name && (
                    <span className="ml-1">({genStatus.current_branch_name})</span>
                  )}
                </p>
              </>
            )}
          </>
        ) : isCompleted ? (
          <p className="text-sm text-[#22C55E]">Генерация завершена. Загрузка данных...</p>
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

function RegenerateButton({
  fromDate,
  toDate,
  onComplete,
}: {
  fromDate: string;
  toDate: string;
  onComplete: () => void;
}) {
  const [starting, setStarting] = useState(false);
  const { genStatus, startPolling } = useGenerationPoller(onComplete);

  const handleRegenerate = async () => {
    setStarting(true);
    try {
      await api.generateForecast({
        from_date: fromDate,
        to_date: toDate,
      });
      startPolling();
    } catch {
      // silently ignore — user can retry
    } finally {
      setStarting(false);
    }
  };

  const isRunning = genStatus?.status === 'running';

  return (
    <button
      onClick={handleRegenerate}
      disabled={starting || isRunning}
      className="px-4 py-2 text-sm border border-[#E2E8F0] rounded-lg text-[#64748B] hover:bg-[#F8FAFC] hover:text-[#0F172A] disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {isRunning
        ? `Генерация... ${genStatus.progress}/${genStatus.total_branches}`
        : 'Обновить прогноз'}
    </button>
  );
}
