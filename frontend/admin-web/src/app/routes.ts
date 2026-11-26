/* Pure route model for the administration shell. */
export type Ownership = "unclaimed" | "mine";

export type AdminRoute =
  | { name: "reviews"; ownership: Ownership }
  | { name: "review"; auditId: string }
  | { name: "categories" }
  | { name: "banned" }
  | { name: "statistics" };

function parseOwnership(value: string | null): Ownership {
  return value === "mine" ? "mine" : "unclaimed";
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
  if (segments[0] === "categories") return { name: "categories" };
  if (segments[0] === "banned") return { name: "banned" };
  if (segments[0] === "statistics") return { name: "statistics" };
  return { name: "reviews", ownership: "unclaimed" };
}

/** Canonical hash for a route, used by links and programmatic navigation. */
export function routeHref(route: AdminRoute): string {
  switch (route.name) {
    case "review":
      return `#/reviews/${encodeURIComponent(route.auditId)}`;
    case "reviews":
      return `#/reviews?ownership=${route.ownership}`;
    case "categories":
      return "#/categories";
    case "banned":
      return "#/banned";
    case "statistics":
      return "#/statistics";
  }
}
