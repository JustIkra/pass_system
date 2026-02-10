import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';

const OverviewPage = lazy(() => import('./pages/OverviewPage'));
const BranchPage = lazy(() => import('./pages/BranchPage'));
const ComparePage = lazy(() => import('./pages/ComparePage'));
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'));

function PageSpinner() {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="w-8 h-8 border-3 border-[#2563EB] border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route
            path="/"
            element={
              <Suspense fallback={<PageSpinner />}>
                <OverviewPage />
              </Suspense>
            }
          />
          <Route
            path="/branches/:id"
            element={
              <Suspense fallback={<PageSpinner />}>
                <BranchPage />
              </Suspense>
            }
          />
          <Route
            path="/compare"
            element={
              <Suspense fallback={<PageSpinner />}>
                <ComparePage />
              </Suspense>
            }
          />
          <Route
            path="*"
            element={
              <Suspense fallback={<PageSpinner />}>
                <NotFoundPage />
              </Suspense>
            }
          />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
