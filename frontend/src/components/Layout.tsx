import { useState } from 'react';
import { Outlet, useOutletContext } from 'react-router-dom';
import Sidebar from './Sidebar';
import TopBar from './TopBar';

interface LayoutContext {
  selectedMonth: string;
  setSelectedMonth: (month: string) => void;
  pageTitle: string;
  setPageTitle: (title: string) => void;
}

export function useLayoutContext() {
  return useOutletContext<LayoutContext>();
}

function getDefaultMonth(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth() + 1;
  return `${y}-${String(m).padStart(2, '0')}`;
}

export default function Layout() {
  const [collapsed, setCollapsed] = useState(false);
  const [selectedMonth, setSelectedMonth] = useState(getDefaultMonth());
  const [pageTitle, setPageTitle] = useState('Обзор сети МФЦ');

  return (
    <div className="flex h-screen bg-[#F8FAFC]">
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <TopBar
          title={pageTitle}
          selectedMonth={selectedMonth}
          onMonthChange={setSelectedMonth}
        />
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet
            context={{ selectedMonth, setSelectedMonth, pageTitle, setPageTitle }}
          />
        </main>
      </div>
    </div>
  );
}
