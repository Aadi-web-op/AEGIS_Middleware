/**
 * Hash routing without a dependency.
 *   #page            -> { page, args: [] }
 *   #page/a/b        -> { page, args: ["a", "b"] }  (args are URI-decoded)
 */
import { useEffect, useState } from "react";

export const PAGES = [
  "overview",
  "evaluate",
  "decisions",
  "intelligence",
  "graph",
  "documents",
  "escalations",
  "system",
];

export function parseHash(hash) {
  const raw = (hash || "").replace(/^#\/?/, "");
  const [page, ...rest] = raw.split("/");
  if (!PAGES.includes(page)) return { page: "overview", args: [] };
  return {
    page,
    args: rest.filter(Boolean).map((s) => {
      try {
        return decodeURIComponent(s);
      } catch {
        return s;
      }
    }),
  };
}

export function href(page, ...args) {
  return `#${[page, ...args.map((a) => encodeURIComponent(a))].join("/")}`;
}

export function go(page, ...args) {
  window.location.hash = href(page, ...args);
}

export function useHashRoute() {
  const [route, setRoute] = useState(() => parseHash(window.location.hash));
  useEffect(() => {
    const raw = window.location.hash.replace(/^#\/?/, "").split("/")[0];
    if (!PAGES.includes(raw)) window.history.replaceState(null, "", "#overview");
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
