/* Pure route model for the administration shell. */
import type { TodoKind, WorkbenchOwnership } from "../api/contracts";

export type Ownership = "unclaimed" | "mine";

export type AdminRoute =
  | { name: "reviews"; ownership: Ownership }
  | { name: "review"; auditId: string }
  | { name: "cases"; ownership: WorkbenchOwnership; kind: TodoKind; keyword: string }
  | { name: "categories" }
  | { name: "banned" };

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

/** Parse a location hash into the page the shell should render. */
export function parseHash(hash: string): AdminRoute {
  const clean = hash.replace(/^#\/?/, "");
  const [pathPart, queryPart] = clean.split("?");
  const segments = pathPart.split("/").filter(Boolean);
  const query = new URLSearchParams(queryPart ?? "");
  if (segments[0] === "reviews" && segments[1]) {
    return { name: "review", auditId: decodeURIComponent(segments[1]) };
  }
  if (segments[0] === "reviews") {
    return { name: "reviews", ownership: parseOwnership(query.get("ownership")) };
  }
  if (segments[0] === "cases") {
    return {
      name: "cases",
      ownership: parseWorkbenchOwnership(query.get("ownership")),
      kind: parseTodoKind(query.get("kind")),
      keyword: (query.get("keyword") ?? "").trim(),
    };
  }
  if (segments[0] === "categories") return { name: "categories" };
  if (segments[0] === "banned") return { name: "banned" };
  return { name: "reviews", ownership: "unclaimed" };
}

/** Canonical hash for a route, used by links and programmatic navigation. */
export function routeHref(route: AdminRoute): string {
  switch (route.name) {
    case "review":
      return `#/reviews/${encodeURIComponent(route.auditId)}`;
    case "reviews":
      return `#/reviews?ownership=${route.ownership}`;
    case "cases": {
      const query = new URLSearchParams({ ownership: route.ownership, kind: route.kind });
      const keyword = route.keyword.trim();
      if (keyword) query.set("keyword", keyword);
      return `#/cases?${query.toString()}`;
    }
    case "categories":
      return "#/categories";
    case "banned":
      return "#/banned";
  }
}
