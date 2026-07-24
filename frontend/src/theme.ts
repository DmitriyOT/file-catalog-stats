import { useCallback, useState } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "theme";

/** Начальная тема уже выставлена inline-скриптом в index.html (localStorage / prefers-color-scheme) */
function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

/** Текущая тема и переключатель; выбор сохраняется в localStorage */
export function useTheme(): { theme: Theme; toggleTheme: () => void } {
  const [theme, setTheme] = useState<Theme>(currentTheme);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => {
      const next: Theme = prev === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {
        // localStorage недоступен — тема просто не сохранится между визитами
      }
      return next;
    });
  }, []);

  return { theme, toggleTheme };
}
