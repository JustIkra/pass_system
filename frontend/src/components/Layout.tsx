import { useState } from 'react';
import { Outlet, useOutletContext } from 'react-router-dom';
import Sidebar from './Sidebar';
import TopBar from './TopBar';

export interface DateRange {
  from: string;
  to: string;
}

interface LayoutContext {
  dateRange: DateRange;
  setDateRange: (range: DateRange) => void;
  pageTitle: string;
  setPageTitle: (title: string) => void;
}

export function useLayoutContext() {
  return useOutletContext<LayoutContext>();
}

function formatDateISO(d: Date): string {
  const y = d.getFullYear();
  const m = (d.getMonth() + 1).toString().padStart(2, '0');
  const day = d.getDate().toString().padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function getDefaultDateRange(): DateRange {
  const now = new Date();
  const from = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const to = new Date(from);
  to.setDate(to.getDate() + 30);
  return {
    from: formatDateISO(from),
    to: formatDateISO(to),
  };
}

export default function Layout() {
  const [collapsed, setCollapsed] = useState(false);
  const [dateRange, setDateRange] = useState<DateRange>(getDefaultDateRange());
  const [pageTitle, setPageTitle] = useState('Обзор сети МФЦ');

  return (
    <div className="flex h-screen bg-[#F8FAFC]">
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <TopBar
          title={pageTitle}
          dateRange={dateRange}
          onDateRangeChange={setDateRange}
        />
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet
            context={{ dateRange, setDateRange, pageTitle, setPageTitle }}
          />
        </main>
      </div>
    </div>
  );
}
