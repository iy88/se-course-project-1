/* Reactive History navigation for the administration shell. */
import { readonly, ref } from "vue";
import { parseLocation, routeHref, type AdminRoute } from "./routes";

function currentLocation(): string {
  const { pathname, search, hash } = window.location;
  return pathname + search + hash;
}

function readLocation(): AdminRoute {
  const location = currentLocation();
  const next = parseLocation(location);
  if (/^\/reviews\/?(?:[?#]|$)/.test(location)) {
    window.history.replaceState(window.history.state, "", routeHref(next));
  }
  return next;
}

const current = ref<AdminRoute>(
  typeof window === "undefined" ? parseLocation("/") : readLocation(),
);

if (typeof window !== "undefined") {
  const sync = () => {
    current.value = readLocation();
  };
  window.addEventListener("popstate", sync);
  window.addEventListener("hashchange", sync);
  document.addEventListener("click", (event) => {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey ||
      !(event.target instanceof Element)
    )
      return;
    const link = event.target.closest<HTMLAnchorElement>("a[data-admin-route]");
    if (
      !link ||
      link.target ||
      link.hasAttribute("download") ||
      link.origin !== window.location.origin
    )
      return;
    event.preventDefault();
    navigate(parseLocation(link.pathname + link.search + link.hash));
  });
}

export const route = readonly(current);

export function navigate(next: AdminRoute): void {
  const href = routeHref(next);
  if (currentLocation() !== href) {
    window.history.pushState(null, "", href);
    if (next.name !== "case" || !next.anchor) window.scrollTo(0, 0);
  }
  current.value = next;
}
