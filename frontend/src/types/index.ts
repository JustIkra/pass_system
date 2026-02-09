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
  predicted_avg_wait: number;
  confidence_lower: number;
  confidence_upper: number;
}

export interface ForecastSummary {
  total_predicted_visits: number;
  peak_day: string;
  peak_hour: number;
  avg_daily_visits: number;
}

export interface ForecastResponse {
  branch_id: number;
  branch_name: string;
  month: string;
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
  month: string;
  windows: WindowLoad[];
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
  month: string;
  recommendations: StaffingRecommendation[];
}

// === Исторические данные ===

export interface DailyHistory {
  date: string;
  total_visits: number;
  avg_wait_minutes: number | null;
  avg_service_minutes: number | null;
  peak_hour: number;
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
  period: { from: string; to: string };
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
}

export interface ComparisonResponse {
  month: string;
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
  month: string;
  total_branches: number;
  total_predicted_visits: number;
  avg_predicted_wait: number;
  top_overloaded: OverloadedBranch[];
  top_underloaded: UnderloadedBranch[];
}

// === Общие типы UI ===

export type LoadLevel = 'critical' | 'high' | 'normal' | 'low' | 'idle';

export interface ApiErrorResponse {
  detail: string;
}
