import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { getJobStatus, JobStatus } from "../api/client";

const POLL_INTERVAL_MS = 1500;

interface JobStatusContextValue {
  job: JobStatus | null;
  /** Перезапросить статус сейчас; если задача выполняется — включает polling */
  refresh: () => Promise<void>;
}

const JobStatusContext = createContext<JobStatusContextValue | null>(null);

/** Единый источник статуса задачи: опрашивает /api/job/status, пока задача выполняется */
export function JobStatusProvider({ children }: { children: ReactNode }) {
  const [job, setJob] = useState<JobStatus | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (timer.current !== null) {
      clearInterval(timer.current);
      timer.current = null;
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const status = await getJobStatus();
      setJob(status);
      if (status?.status === "running") {
        // активная задача — продолжаем опрос, пока не завершится
        if (timer.current === null) timer.current = setInterval(refresh, POLL_INTERVAL_MS);
      } else {
        stopPolling();
      }
    } catch {
      // индикатор — не критично, просто пропускаем цикл
    }
  }, [stopPolling]);

  useEffect(() => {
    refresh();
    return stopPolling;
  }, [refresh, stopPolling]);

  const value = useMemo(() => ({ job, refresh }), [job, refresh]);

  return <JobStatusContext.Provider value={value}>{children}</JobStatusContext.Provider>;
}

export function useJobStatus(): JobStatusContextValue {
  const ctx = useContext(JobStatusContext);
  if (!ctx) throw new Error("useJobStatus должен использоваться внутри JobStatusProvider");
  return ctx;
}
