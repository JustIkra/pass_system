import { useEffect, useState, useMemo } from 'react';
import { useLayoutContext } from '../components/Layout';
import { useApi } from '../hooks/useApi';
import { api } from '../api/client';
import BarChart from '../components/BarChart';
import LoadIndicator from '../components/LoadIndicator';
import type { Branch, ComparisonResponse } from '../types';

function formatNum(n: number): string {
  return Math.round(n)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

function formatWait(minutes: number): string {
  return minutes.toFixed(1).replace('.', ',') + ' мин';
}

type MetricKey = 'visits' | 'wait' | 'windows';

export default function ComparePage() {
  const { dateRange, setPageTitle } = useLayoutContext();
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [metric, setMetric] = useState<MetricKey>('visits');

  useEffect(() => {
    setPageTitle('Сравнение филиалов');
  }, [setPageTitle]);

  const { data: branches } = useApi<Branch[]>(() => api.getBranches(), []);

  const {
    data: comparison,
    loading: compareLoading,
    error: compareError,
    refetch,
  } = useApi<ComparisonResponse>(
    () =>
      selectedIds.length >= 2
        ? api.compareBranches(selectedIds, dateRange.from, dateRange.to)
        : Promise.resolve({ from_date: dateRange.from, to_date: dateRange.to, branches: [] }),
    [selectedIds, dateRange.from, dateRange.to]
  );

  const toggleBranch = (id: number) => {
    setSelectedIds((prev) => {
      if (prev.includes(id)) {
        return prev.filter((x) => x !== id);
      }
      if (prev.length >= 5) return prev;
      return [...prev, id];
    });
  };

  const barData = useMemo(() => {
    if (!comparison?.branches) return [];
    return comparison.branches.map((b) => ({
      name: b.name,
      value:
        metric === 'visits'
          ? b.predicted_total_visits
          : metric === 'wait'
            ? (b.predicted_avg_wait ?? 0)
            : b.required_avg_windows,
    }));
  }, [comparison, metric]);

  const barTitle =
    metric === 'visits'
      ? 'Прогноз обращений'
      : metric === 'wait'
        ? 'Среднее ожидание (мин)'
        : 'Требуемые окна (ср.)';

  return (
    <div className="space-y-6">
      {/* Branch selector */}
      <div className="bg-white rounded-lg shadow-sm border border-[#E2E8F0] p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-[#0F172A]">
            Выберите филиалы для сравнения (2-5)
          </h2>
          <span className="text-xs text-[#64748B]">
            Выбрано: {selectedIds.length} из 5
          </span>
        </div>
        {/* Selected tags */}
        {selectedIds.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-3">
            {selectedIds.map((id) => {
              const br = branches?.find((b) => b.id === id);
              return (
                <span
                  key={id}
                  className="inline-flex items-center gap-1 px-2.5 py-1 bg-[#EFF6FF] text-[#2563EB] text-xs rounded-full"
                >
                  {br?.name ?? `ID ${id}`}
                  <button
                    onClick={() => toggleBranch(id)}
                    className="ml-1 text-[#2563EB] hover:text-[#1D4ED8]"
                  >
                    x
                  </button>
                </span>
              );
            })}
          </div>
        )}
        {/* Branch grid */}
        <div className="max-h-60 overflow-y-auto border border-[#E2E8F0] rounded">
          {branches?.map((b) => (
            <label
              key={b.id}
              className="flex items-center gap-3 px-3 py-2 hover:bg-[#F8FAFC] cursor-pointer border-b border-[#F1F5F9] last:border-b-0"
            >
              <input
                type="checkbox"
                checked={selectedIds.includes(b.id)}
                onChange={() => toggleBranch(b.id)}
                disabled={
                  !selectedIds.includes(b.id) && selectedIds.length >= 5
                }
                className="accent-[#2563EB]"
              />
              <span className="text-sm text-[#0F172A]">{b.name}</span>
            </label>
          ))}
        </div>
      </div>

      {selectedIds.length < 2 && (
        <div className="text-center text-[#64748B] py-8 text-sm">
          Выберите минимум 2 филиала для сравнения
        </div>
      )}

      {selectedIds.length >= 2 && (
        <>
          {/* Metric switcher */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-[#64748B]">Метрика:</span>
            {(
              [
                { key: 'visits', label: 'Обращения' },
                { key: 'wait', label: 'Ожидание' },
                { key: 'windows', label: 'Окна' },
              ] as const
            ).map((m) => (
              <button
                key={m.key}
                onClick={() => setMetric(m.key)}
                className={`px-3 py-1.5 text-xs rounded border ${
                  metric === m.key
                    ? 'bg-[#2563EB] text-white border-[#2563EB]'
                    : 'bg-white text-[#64748B] border-[#E2E8F0] hover:border-[#2563EB]'
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>

          {compareLoading && (
            <div className="flex items-center justify-center h-48">
              <div className="w-8 h-8 border-3 border-[#2563EB] border-t-transparent rounded-full animate-spin" />
            </div>
          )}

          {compareError && (
            <div className="text-center">
              <p className="text-[#EF4444] mb-3">{compareError}</p>
              <button
                onClick={refetch}
                className="px-4 py-2 bg-[#2563EB] text-white rounded text-sm"
              >
                Повторить
              </button>
            </div>
          )}

          {!compareLoading && !compareError && comparison && (
            <>
              <BarChart data={barData} title={barTitle} yAxisLabel={barTitle} />

              {/* Comparison table */}
              <div className="bg-white rounded-lg shadow-sm border border-[#E2E8F0] overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[#E2E8F0] text-[#64748B]">
                      <th className="text-left px-4 py-3 font-medium">
                        Филиал
                      </th>
                      <th className="text-right px-4 py-3 font-medium">
                        Обращений
                      </th>
                      <th className="text-right px-4 py-3 font-medium">
                        Ожидание
                      </th>
                      <th className="text-right px-4 py-3 font-medium">
                        Обслуживание
                      </th>
                      <th className="text-center px-4 py-3 font-medium">
                        Пик. час
                      </th>
                      <th className="text-center px-4 py-3 font-medium">
                        Окна (ср.)
                      </th>
                      <th className="text-center px-4 py-3 font-medium">
                        Перегруж. часов
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparison.branches.map((b, idx) => (
                      <tr
                        key={b.id}
                        className={`border-b border-[#F1F5F9] ${
                          idx === 0 ? 'font-semibold' : ''
                        }`}
                      >
                        <td className="px-4 py-2.5 text-[#0F172A]">
                          <span className="flex items-center gap-2">
                            <LoadIndicator
                              value={b.load_percent ?? 0}
                              size="sm"
                            />
                            {b.name}
                          </span>
                        </td>
                        <td className="text-right px-4 py-2.5 text-[#0F172A]">
                          {formatNum(b.predicted_total_visits)}
                        </td>
                        <td className="text-right px-4 py-2.5 text-[#0F172A]">
                          {b.predicted_avg_wait != null ? formatWait(b.predicted_avg_wait) : '-'}
                        </td>
                        <td className="text-right px-4 py-2.5 text-[#0F172A]">
                          {b.predicted_avg_service != null ? formatWait(b.predicted_avg_service) : '-'}
                        </td>
                        <td className="text-center px-4 py-2.5 text-[#0F172A]">
                          {b.predicted_peak_hour != null ? `${b.predicted_peak_hour}:00` : '-'}
                        </td>
                        <td className="text-center px-4 py-2.5 text-[#0F172A]">
                          {b.required_avg_windows}
                        </td>
                        <td className="text-center px-4 py-2.5 text-[#0F172A]">
                          {b.overloaded_hours_count}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
