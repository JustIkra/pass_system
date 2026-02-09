import { useState, useMemo } from 'react';
import { NavLink, Link } from 'react-router-dom';
import { useApi } from '../hooks/useApi';
import { api } from '../api/client';

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export default function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const [search, setSearch] = useState('');
  const { data: branches, loading } = useApi(() => api.getBranches(), []);

  const filtered = useMemo(() => {
    if (!branches) return [];
    if (!search.trim()) return branches;
    const q = search.toLowerCase();
    return branches.filter(
      (b) =>
        b.name.toLowerCase().includes(q) ||
        (b.depart_name_mfc?.toLowerCase().includes(q) ?? false)
    );
  }, [branches, search]);

  return (
    <aside
      className={`bg-[#1E293B] text-white flex flex-col shrink-0 transition-all duration-200 ${
        collapsed ? 'w-16' : 'w-[280px]'
      }`}
      style={{ height: '100vh', position: 'sticky', top: 0 }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 h-14 border-b border-[#334155]">
        {!collapsed && (
          <Link to="/" className="text-base font-bold text-white hover:text-blue-300 truncate">
            МФЦ Прогноз
          </Link>
        )}
        <button
          onClick={onToggle}
          className="text-[#94A3B8] hover:text-white p-1"
          title={collapsed ? 'Развернуть' : 'Свернуть'}
        >
          <svg
            width="20"
            height="20"
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            {collapsed ? (
              <path d="M7 4l6 6-6 6" />
            ) : (
              <path d="M13 4l-6 6 6 6" />
            )}
          </svg>
        </button>
      </div>

      {/* Search */}
      {!collapsed && (
        <div className="px-3 py-3">
          <input
            type="text"
            placeholder="Поиск филиала..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full px-3 py-2 bg-[#334155] text-white text-sm rounded border border-[#475569] placeholder-[#94A3B8] focus:outline-none focus:border-[#2563EB]"
          />
        </div>
      )}

      {/* Overview link */}
      <div className="px-3 mb-1">
        <NavLink
          to="/"
          end
          className={({ isActive }) =>
            `flex items-center gap-3 px-3 py-2 rounded text-sm transition-colors ${
              isActive
                ? 'bg-[#2563EB] text-white'
                : 'text-[#CBD5E1] hover:bg-[#334155] hover:text-white'
            }`
          }
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <path d="M2 2h5v5H2V2zm7 0h5v5H9V2zM2 9h5v5H2V9zm7 0h5v5H9V9z" />
          </svg>
          {!collapsed && <span>Все филиалы</span>}
        </NavLink>
      </div>

      {/* Branch list */}
      <div className="flex-1 overflow-y-auto px-3 space-y-0.5">
        {loading && !collapsed && (
          <div className="text-sm text-[#94A3B8] px-3 py-2">Загрузка...</div>
        )}
        {filtered.map((branch) => (
          <NavLink
            key={branch.id}
            to={`/branches/${branch.id}`}
            className={({ isActive }) =>
              `flex items-center gap-2 px-3 py-2 rounded text-sm transition-colors truncate ${
                isActive
                  ? 'bg-[#2563EB] text-white'
                  : 'text-[#CBD5E1] hover:bg-[#334155] hover:text-white'
              }`
            }
            title={branch.name}
          >
            {!collapsed && <span className="truncate">{branch.name}</span>}
          </NavLink>
        ))}
        {!loading && filtered.length === 0 && !collapsed && (
          <div className="text-sm text-[#94A3B8] px-3 py-2">
            Филиалы не найдены
          </div>
        )}
      </div>

      {/* Compare link */}
      <div className="px-3 py-3 border-t border-[#334155]">
        <NavLink
          to="/compare"
          className={({ isActive }) =>
            `flex items-center gap-3 px-3 py-2 rounded text-sm transition-colors ${
              isActive
                ? 'bg-[#2563EB] text-white'
                : 'text-[#CBD5E1] hover:bg-[#334155] hover:text-white'
            }`
          }
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <path d="M1 12h3V5H1v7zm4 0h3V1H5v11zm4 0h3V8H9v4zm4 0h2V3h-2v9z" />
          </svg>
          {!collapsed && <span>Сравнение филиалов</span>}
        </NavLink>
      </div>
    </aside>
  );
}
