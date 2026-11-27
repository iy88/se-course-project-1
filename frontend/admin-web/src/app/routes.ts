/* Pure route model for the administration shell. */
import type { TodoKind, WorkbenchOwnership } from "../api/contracts";

export type Ownership = "unclaimed" | "mine";

export interface WorkbenchFilters {
  ownership: WorkbenchOwnership;
  kind: TodoKind;
  keyword: string;
}

export type AdminRoute =
  | { name: "review"; auditId: string }
  | ({ name: "cases" } & WorkbenchFilters)
  | ({ name: "case"; caseId: string; anchor?: string } & WorkbenchFilters)
  | { name: "categories" }
  | { name: "banned" }
  | { name: "statistics" }
  | { name: "notifications"; notificationId?: string };

const WORKBENCH_OWNERSHIP: WorkbenchOwnership[] = [
  "unclaimed",
  "mine",
  "completed_mine",
  "completed_all",
];

const TODO_KINDS: TodoKind[] = ["all", "product_review", "report", "dispute", "exception"];

function parseOwnership(value: string | null): Ownership {
  return value === "mine" ? "mine" : "unclaimed";
}

export function parseWorkbenchOwnership(value: string | null): WorkbenchOwnership {
  return WORKBENCH_OWNERSHIP.find((option) => option === value) ?? "unclaimed";
}

export function parseTodoKind(value: string | null): TodoKind {
  return TODO_KINDS.find((option) => option === value) ?? "all";
}

/** Parse a browser location into the page the shell should render. */
export function parseLocation(location: string): AdminRoute {
  const [clean, anchor] = location.split("#");
  const [pathPart, queryPart] = clean.split("?");
  const segments = pathPart.split("/").filter(Boolean);
  const query = new URLSearchParams(queryPart ?? "");
  if (segments[0] === "reviews" && segments[1]) {
    return { name: "review", auditId: decodeURIComponent(segments[1]) };
  }
  if (segments[0] === "reviews") {
    return reviewWorkbench(parseOwnership(query.get("ownership")));
  }
  if (segments[0] === "cases") {
    const filters = {
      ownership: parseWorkbenchOwnership(query.get("ownership")),
      kind: parseTodoKind(query.get("kind")),
      keyword: (query.get("keyword") ?? "").trim(),
    };
    return segments[1] && /^[1-9][0-9]*$/.test(segments[1])
      ? {
          name: "case",
          caseId: segments[1],
          ...filters,
          ...(anchor && /^case-(action|supplement|evidence|message)-[1-9][0-9]*$/.test(anchor)
            ? { anchor }
            : {}),
        }
      : { name: "cases", ...filters };
  }
  if (segments[0] === "notifications") {
    return segments[1] && /^[1-9][0-9]*$/.test(segments[1])
      ? { name: "notifications", notificationId: segments[1] }
      : { name: "notifications" };
  }
  if (segments[0] === "categories") return { name: "categories" };
  if (segments[0] === "banned") return { name: "banned" };
  if (segments[0] === "statistics") return { name: "statistics" };
  return { name: "cases", ownership: "unclaimed", kind: "all", keyword: "" };
}

export function reviewWorkbench(ownership: Ownership): AdminRoute {
  return { name: "cases", ownership, kind: "product_review", keyword: "" };
}

/** Canonical URL for a route, used by links and programmatic navigation. */
export function routeHref(route: AdminRoute): string {
  switch (route.name) {
    case "review":
      return `/reviews/${encodeURIComponent(route.auditId)}`;
    case "cases":
    case "case": {
      const query = new URLSearchParams({ ownership: route.ownership, kind: route.kind });
      const keyword = route.keyword.trim();
      if (keyword) query.set("keyword", keyword);
      const path = route.name === "case" ? `/cases/${encodeURIComponent(route.caseId)}` : "/cases";
      const anchor = route.name === "case" && route.anchor ? `#${route.anchor}` : "";
      return `${path}?${query.toString()}${anchor}`;
    }
    case "categories":
      return "/categories";
    case "banned":
      return "/banned";
    case "notifications":
      return route.notificationId ? `/notifications/${route.notificationId}` : "/notifications";
    case "statistics":
      return "/statistics";
  }
}
