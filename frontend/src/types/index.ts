// === Базовые типы ===

export interface Branch {
  id: number;
  name: string;
  depart_name_mfc: string | null;
  total_records: number;
  date_range: { from_date: string; to_date: string };
}

export interface BranchDetail extends Branch {
  num_employees: number;
  num_windows: number;
  avg_daily_visits: number;
  avg_wait_minutes: number;
  avg_service_minutes: number;
  top_services: ServiceStat[];
}

export interface ServiceStat {
  service_id: number;
  service_name: string;
  count: number;
}

// === Прогноз ===

export interface ForecastPoint {
  date: string;
  hour: number;
  predicted_visits: number;
  predicted_avg_wait: number | null;
  confidence_lower: number | null;
  confidence_upper: number | null;
}

export interface ForecastSummary {
  total_predicted_visits: number;
  peak_day: string | null;
  peak_hour: number | null;
  avg_daily_visits: number;
}

export interface ForecastResponse {
  branch_id: number;
  branch_name: string;
  from_date: string;
  to_date: string;
  data: ForecastPoint[];
  summary: ForecastSummary;
}

// === Загрузка окон ===

export interface WindowHourLoad {
  hour: number;
  load_percent: number;
  avg_visits: number;
}

export interface WindowLoad {
  window_number: string;
  avg_daily_load_percent: number;
  load_by_hour: WindowHourLoad[];
  status: 'overloaded' | 'normal' | 'underloaded' | 'idle';
}

export interface WindowsResponse {
  branch_id: number;
  from_date: string;
  to_date: string;
  windows: WindowLoad[];
  data_source: 'forecast' | 'history';
}

// === Рекомендации по штату ===

export interface StaffingRecommendation {
  date: string;
  hour: number;
  predicted_visits: number;
  avg_service_minutes: number;
  required_windows: number;
  current_windows_avg: number;
  delta: number;
  status: 'understaffed' | 'optimal' | 'overstaffed';
}

export interface StaffingResponse {
  branch_id: number;
  from_date: string;
  to_date: string;
  recommendations: StaffingRecommendation[];
}

// === Исторические данные ===

export interface DailyHistory {
  date: string;
  total_visits: number;
  avg_wait_minutes: number | null;
  avg_service_minutes: number | null;
  peak_hour: number | null;
}

export interface HourlyHistory {
  date: string;
  hour: number;
  total_visits: number;
  avg_wait_minutes: number | null;
  avg_service_minutes: number | null;
  num_windows_active: number;
}

export interface HistoryResponse {
  branch_id: number;
  period: { from_date: string; to_date: string };
  daily: DailyHistory[];
  hourly: HourlyHistory[];
}

// === Сравнение ===

export interface BranchComparison {
  id: number;
  name: string;
  predicted_total_visits: number;
  predicted_avg_wait: number | null;
  predicted_avg_service: number | null;
  predicted_peak_hour: number | null;
  required_avg_windows: number;
  overloaded_hours_count: number;
  load_percent: number | null;
}

export interface ComparisonResponse {
  from_date: string;
  to_date: string;
  branches: BranchComparison[];
}

// === Обзор ===

export interface OverloadedBranch {
  branch_id: number;
  branch_name: string;
  predicted_avg_wait: number;
  overloaded_hours: number;
}

export interface UnderloadedBranch {
  branch_id: number;
  branch_name: string;
  predicted_avg_wait: number;
  avg_load_percent: number;
}

export interface OverviewResponse {
  from_date: string;
  to_date: string;
  total_branches: number;
  total_predicted_visits: number;
  avg_predicted_wait: number;
  top_overloaded: OverloadedBranch[];
  top_underloaded: UnderloadedBranch[];
}

// === Генерация прогноза ===

export interface ForecastGenerateRequest {
  from_date: string;
  to_date: string;
  branch_id?: number | null;
}

export interface ForecastGenerateResponse {
  status: string;
  message: string;
  total_branches: number;
}

export interface ForecastGenerationStatus {
  status: 'idle' | 'running' | 'completed' | 'error';
  progress: number;
  total_branches: number;
  current_branch_name: string | null;
  started_at: string | null;
  error_message: string | null;
}

// === Общие типы UI ===

export type LoadLevel = 'critical' | 'high' | 'normal' | 'low' | 'idle';

export interface ApiErrorResponse {
  detail: string;
}
