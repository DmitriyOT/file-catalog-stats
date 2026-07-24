import { useCallback, useEffect, useRef, useState } from "react";
import { FilePage, getFiles, getStats, StatsResponse } from "../api/client";
import StatsPanel from "../components/StatsPanel";

const PER_PAGE = 20;
const SEARCH_DEBOUNCE_MS = 400;

/** Номера страниц с многоточиями: 1 … 4 5 [6] 7 8 … 42 */
function pageWindow(page: number, pages: number): (number | "…")[] {
  if (pages <= 9) return Array.from({ length: pages }, (_, i) => i + 1);
  const near = new Set(
    [1, 2, page - 2, page - 1, page, page + 1, page + 2, pages - 1, pages].filter(
      (p) => p >= 1 && p <= pages,
    ),
  );
  const sorted = [...near].sort((a, b) => a - b);
  const out: (number | "…")[] = [];
  let prev = 0;
  for (const p of sorted) {
    if (p - prev > 1) out.push("…");
    out.push(p);
    prev = p;
  }
  return out;
}

export default function FilesPage() {
  const [data, setData] = useState<FilePage | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<"asc" | "desc">("asc");
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [selectAll, setSelectAll] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [calculating, setCalculating] = useState(false);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++requestSeq.current;
    setLoading(true);
    try {
      const result = await getFiles(page, PER_PAGE, sort, search);
      // поздний ответ устаревшего запроса не должен перезаписать более свежий
      if (seq === requestSeq.current) {
        setData(result);
        setLoadError(null);
      }
    } catch (e) {
      if (seq === requestSeq.current)
        setLoadError(e instanceof Error ? e.message : String(e));
    } finally {
      // индикатор снимает только последний (актуальный) запрос
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [page, sort, search]);

  useEffect(() => {
    load();
  }, [load]);

  // при размонтировании отменяем отложенное применение поиска
  useEffect(
    () => () => {
      if (debounce.current) clearTimeout(debounce.current);
    },
    [],
  );

  // Поиск с debounce: применяем через 400 мс после последнего символа
  const handleSearchChange = (value: string) => {
    setSearchInput(value);
    if (debounce.current) clearTimeout(debounce.current);
    debounce.current = setTimeout(() => {
      setPage(1);
      setSearch(value.trim());
    }, SEARCH_DEBOUNCE_MS);
  };

  const toggleOne = (id: number) => {
    setSelectAll(false);
    setStats(null);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const pageIds = data?.items.map((f) => f.id) ?? [];
  const allOnPageSelected = pageIds.length > 0 && pageIds.every((id) => selected.has(id));

  const togglePage = () => {
    setSelectAll(false);
    setStats(null);
    setSelected((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) pageIds.forEach((id) => next.delete(id));
      else pageIds.forEach((id) => next.add(id));
      return next;
    });
  };

  const toggleAll = () => {
    setSelectAll((prev) => !prev);
    setStats(null);
    setSelected(new Set());
  };

  const chosenCount = selectAll ? (data?.total ?? 0) : selected.size;

  const handleCalculate = async () => {
    setError(null);
    setCalculating(true);
    try {
      setStats(await getStats(selectAll ? [] : [...selected], selectAll));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCalculating(false);
    }
  };

  return (
    <section>
      <h2>Скачанные файлы</h2>
      {error && <p className="error">{error}</p>}
      {loadError && (
        <div className="error-block">
          <p className="error">Не удалось загрузить список файлов: {loadError}</p>
          <button onClick={load}>Повторить</button>
        </div>
      )}

      <div className="toolbar">
        <input
          type="search"
          className="search"
          placeholder="Поиск по имени файла…"
          value={searchInput}
          onChange={(e) => handleSearchChange(e.target.value)}
        />
        <label>
          <input type="checkbox" checked={selectAll} onChange={toggleAll} /> Выбрать вообще все (
          {data?.total ?? 0})
        </label>
        <button disabled={chosenCount === 0 || calculating} onClick={handleCalculate}>
          {calculating ? "Считаю..." : `Произвести расчёты (${chosenCount})`}
        </button>
      </div>

      <table>
        <thead>
          <tr>
            <th>
              <input
                type="checkbox"
                checked={selectAll || allOnPageSelected}
                disabled={selectAll}
                onChange={togglePage}
                title="Выбрать все на странице"
              />
            </th>
            <th>Имя файла</th>
            <th
              className="sortable"
              onClick={() => {
                setPage(1);
                setSort(sort === "asc" ? "desc" : "asc");
              }}
            >
              Время скачивания (НСК) {sort === "asc" ? "▲" : "▼"}
            </th>
          </tr>
        </thead>
        <tbody>
          {data?.items.map((f) => (
            <tr key={f.id}>
              <td>
                <input
                  type="checkbox"
                  checked={selectAll || selected.has(f.id)}
                  disabled={selectAll}
                  onChange={() => toggleOne(f.id)}
                />
              </td>
              <td>{f.name}</td>
              <td>{f.downloaded_at_nsk}</td>
            </tr>
          ))}
          {loading && (
            <tr>
              <td colSpan={3}>Загрузка…</td>
            </tr>
          )}
          {!loading && data?.items.length === 0 && (
            <tr>
              <td colSpan={3}>
                {search ? `Ничего не найдено по запросу «${search}».` : "Файлов пока нет."}
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {data && data.pages > 1 && (
        <div className="pagination">
          <button disabled={page <= 1} onClick={() => setPage(page - 1)}>
            ←
          </button>
          {pageWindow(data.page, data.pages).map((p, i) =>
            p === "…" ? (
              <span key={`gap-${i}`} className="gap">
                …
              </span>
            ) : (
              <button
                key={p}
                className={p === data.page ? "active" : ""}
                onClick={() => setPage(p)}
              >
                {p}
              </button>
            ),
          )}
          <button disabled={page >= data.pages} onClick={() => setPage(page + 1)}>
            →
          </button>
        </div>
      )}

      {stats && <StatsPanel stats={stats} />}
    </section>
  );
}
