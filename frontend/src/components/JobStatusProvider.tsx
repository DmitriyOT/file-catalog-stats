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
/** Сколько подряд неудачных опросов считаем потерей связи с backend */
const MAX_CONSECUTIVE_FAILURES = 3;

interface JobStatusContextValue {
  job: JobStatus | null;
  /** Перезапросить статус сейчас; если задача выполняется — включает polling */
  refresh: () => Promise<void>;
  /** true, если опрос статуса несколько раз подряд завершился ошибкой */
  unreachable: boolean;
}

const JobStatusContext = createContext<JobStatusContextValue | null>(null);

/** Единый источник статуса задачи: опрашивает /api/job/status, пока задача выполняется */
export function JobStatusProvider({ children }: { children: ReactNode }) {
  const [job, setJob] = useState<JobStatus | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const failures = useRef(0);

  const refresh = useCallback(async () => {
    try {
      const status = await getJobStatus();
      setJob(status);
      failures.current = 0;
      setUnreachable(false);
    } catch {
      // цикл опроса продолжается, но после нескольких подряд ошибок сообщаем о потере связи
      failures.current += 1;
      if (failures.current >= MAX_CONSECUTIVE_FAILURES) setUnreachable(true);
    }
  }, []);

  // первичный опрос при монтировании
  useEffect(() => {
    void refresh();
  }, [refresh]);

  // активная задача — продолжаем опрос, пока не завершится
  const running = job?.status === "running";
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [running, refresh]);

  const value = useMemo(() => ({ job, refresh, unreachable }), [job, refresh, unreachable]);

  return <JobStatusContext.Provider value={value}>{children}</JobStatusContext.Provider>;
}

export function useJobStatus(): JobStatusContextValue {
  const ctx = useContext(JobStatusContext);
  if (!ctx) throw new Error("useJobStatus должен использоваться внутри JobStatusProvider");
  return ctx;
}
