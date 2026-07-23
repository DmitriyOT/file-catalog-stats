import { StatsResponse } from "../api/client";

const DIGITS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"];

export default function StatsPanel({ stats }: { stats: StatsResponse }) {
  return (
    <div className="card">
      <h3>Результаты расчётов</h3>

      <h4>Общая статистика по {stats.files.length} файлам</h4>
      <table className="stats">
        <thead>
          <tr>
            {DIGITS.map((d) => (
              <th key={d}>{d}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            {DIGITS.map((d) => (
              <td key={d}>{stats.total[d]}</td>
            ))}
          </tr>
        </tbody>
      </table>

      <h4>Статистика по файлам</h4>
      <table className="stats">
        <thead>
          <tr>
            <th>Файл</th>
            {DIGITS.map((d) => (
              <th key={d}>{d}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {stats.files.map((f) => (
            <tr key={f.id}>
              <td>{f.name}</td>
              {DIGITS.map((d) => (
                <td key={d}>{f.counts[d]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
