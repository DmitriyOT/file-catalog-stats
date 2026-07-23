import { useCallback, useEffect, useState } from "react";
import { FilePage, getFiles, getStats, StatsResponse } from "../api/client";
import StatsPanel from "../components/StatsPanel";

const PER_PAGE = 20;

export default function FilesPage() {
  const [data, setData] = useState<FilePage | null>(null);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<"asc" | "desc">("asc");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [selectAll, setSelectAll] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [calculating, setCalculating] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await getFiles(page, PER_PAGE, sort));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [page, sort]);

  useEffect(() => {
    load();
  }, [load]);

  const toggleOne = (id: number) => {
    setSelectAll(false);
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
    setSelected((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) pageIds.forEach((id) => next.delete(id));
      else pageIds.forEach((id) => next.add(id));
      return next;
    });
  };

  const toggleAll = () => {
    setSelectAll((prev) => !prev);
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

      <div className="toolbar">
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
            <th className="sortable" onClick={() => setSort(sort === "asc" ? "desc" : "asc")}>
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
          {data?.items.length === 0 && (
            <tr>
              <td colSpan={3}>Файлов пока нет — запустите скачивание на первой странице.</td>
            </tr>
          )}
        </tbody>
      </table>

      {data && data.pages > 1 && (
        <div className="pagination">
          <button disabled={page <= 1} onClick={() => setPage(page - 1)}>
            ← Назад
          </button>
          <span>
            Страница {data.page} из {data.pages}
          </span>
          <button disabled={page >= data.pages} onClick={() => setPage(page + 1)}>
            Вперёд →
          </button>
        </div>
      )}

      {stats && <StatsPanel stats={stats} />}
    </section>
  );
}
