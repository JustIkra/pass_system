import { Link } from 'react-router-dom';

export default function NotFoundPage() {
  return (
    <div className="flex items-center justify-center h-[60vh]">
      <div className="text-center">
        <h1 className="text-6xl font-bold text-[#E2E8F0] mb-4">404</h1>
        <p className="text-lg text-[#0F172A] mb-2">Страница не найдена</p>
        <p className="text-sm text-[#64748B] mb-6">
          Запрашиваемая страница не существует или была перемещена.
        </p>
        <Link
          to="/"
          className="inline-block px-5 py-2.5 bg-[#2563EB] text-white rounded text-sm font-medium hover:bg-[#1D4ED8] transition-colors"
        >
          На главную
        </Link>
      </div>
    </div>
  );
}
