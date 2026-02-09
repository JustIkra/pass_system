import type {
  Branch,
  BranchDetail,
  ForecastResponse,
  WindowsResponse,
  StaffingResponse,
  HistoryResponse,
  ComparisonResponse,
  OverviewResponse,
} from '../types';

const API_BASE = import.meta.env.VITE_API_URL || '/api';

class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function fetchApi<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    let detail = `Ошибка сервера: ${res.status}`;
    try {
      const json = JSON.parse(text) as { detail?: string };
      if (json.detail) {
        detail = json.detail;
      }
    } catch {
      // ignore parse error
    }
    throw new ApiError(detail, res.status);
  }
  return res.json() as Promise<T>;
}

export const api = {
  getBranches: () => fetchApi<Branch[]>('/branches'),

  getBranch: (id: number) => fetchApi<BranchDetail>(`/branches/${id}`),

  getForecast: (id: number, month: string) =>
    fetchApi<ForecastResponse>(`/branches/${id}/forecast?month=${month}`),

  getWindows: (id: number, month: string) =>
    fetchApi<WindowsResponse>(`/branches/${id}/windows?month=${month}`),

  getStaffing: (id: number, month: string) =>
    fetchApi<StaffingResponse>(`/branches/${id}/staffing?month=${month}`),

  getHistory: (id: number, from: string, to: string) =>
    fetchApi<HistoryResponse>(`/branches/${id}/history?from=${from}&to=${to}`),

  compareBranches: (ids: number[], month: string) =>
    fetchApi<ComparisonResponse>(
      `/branches/compare?ids=${ids.join(',')}&month=${month}`
    ),

  getOverview: (month: string) =>
    fetchApi<OverviewResponse>(`/analytics/overview?month=${month}`),
};

export { ApiError };
