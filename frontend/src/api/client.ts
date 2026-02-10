import type {
  Branch,
  BranchDetail,
  ForecastResponse,
  ForecastGenerateRequest,
  ForecastGenerateResponse,
  ForecastGenerationStatus,
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

async function postApi<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
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

  getForecast: (id: number, fromDate: string, toDate: string) =>
    fetchApi<ForecastResponse>(
      `/branches/${id}/forecast?from_date=${fromDate}&to_date=${toDate}`
    ),

  getWindows: (id: number, fromDate: string, toDate: string) =>
    fetchApi<WindowsResponse>(
      `/branches/${id}/windows?from_date=${fromDate}&to_date=${toDate}`
    ),

  getStaffing: (id: number, fromDate: string, toDate: string) =>
    fetchApi<StaffingResponse>(
      `/branches/${id}/staffing?from_date=${fromDate}&to_date=${toDate}`
    ),

  getHistory: (id: number, from: string, to: string) =>
    fetchApi<HistoryResponse>(
      `/branches/${id}/history?from=${from}&to=${to}`
    ),

  compareBranches: (ids: number[], fromDate: string, toDate: string) =>
    fetchApi<ComparisonResponse>(
      `/branches/compare?ids=${ids.join(',')}&from_date=${fromDate}&to_date=${toDate}`
    ),

  getOverview: (fromDate: string, toDate: string) =>
    fetchApi<OverviewResponse>(
      `/analytics/overview?from_date=${fromDate}&to_date=${toDate}`
    ),

  generateForecast: (req: ForecastGenerateRequest) =>
    postApi<ForecastGenerateResponse>('/forecast/generate', req),

  getForecastGenerationStatus: () =>
    fetchApi<ForecastGenerationStatus>('/forecast/status'),
};

export { ApiError };
