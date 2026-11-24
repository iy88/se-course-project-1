/* Reactive hash navigation for the administration shell. */
import { readonly, ref } from "vue";
import { parseHash, routeHref, type AdminRoute } from "./routes";

const current = ref<AdminRoute>(
  parseHash(typeof window === "undefined" ? "" : window.location.hash),
);

if (typeof window !== "undefined") {
  window.addEventListener("hashchange", () => {
    current.value = parseHash(window.location.hash);
  });
}

export const route = readonly(current);

export function navigate(next: AdminRoute): void {
  const href = routeHref(next);
  if (window.location.hash === href) {
    current.value = next;
    return;
  }
  window.location.hash = href;
}
