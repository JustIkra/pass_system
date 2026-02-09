import { useState, useEffect, useRef, useCallback } from 'react';

interface UseApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

interface UseApiResult<T> extends UseApiState<T> {
  refetch: () => void;
}

/**
 * Custom hook for API calls with loading/error states.
 * Minimum 300ms display time to prevent spinner flicker.
 *
 * @param fetcher - async function that returns data
 * @param deps - dependency array; re-fetches when deps change
 */
export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = []
): UseApiResult<T> {
  const [state, setState] = useState<UseApiState<T>>({
    data: null,
    loading: true,
    error: null,
  });

  const mountedRef = useRef(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  // Serialize deps to a string to use as a stable dependency
  const depsKey = JSON.stringify(deps);

  const execute = useCallback(() => {
    setState((prev) => ({ ...prev, loading: true, error: null }));

    const minDelay = new Promise<void>((resolve) => setTimeout(resolve, 300));

    Promise.all([fetcherRef.current(), minDelay])
      .then(([result]) => {
        if (mountedRef.current) {
          setState({ data: result, loading: false, error: null });
        }
      })
      .catch((err: unknown) => {
        if (mountedRef.current) {
          const message =
            err instanceof Error
              ? err.message
              : 'Не удалось загрузить данные';
          setState({ data: null, loading: false, error: message });
        }
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [depsKey]);

  useEffect(() => {
    mountedRef.current = true;
    execute();
    return () => {
      mountedRef.current = false;
    };
  }, [execute]);

  return {
    ...state,
    refetch: execute,
  };
}
