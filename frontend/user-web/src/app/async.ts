/*
 * Small async state helpers shared by views: one-shot loads and paged lists.
 * They keep the pending/idle/failed transitions identical across screens.
 */
import { computed, reactive, ref, shallowRef, type Ref } from "vue";
import { AbortedError } from "../api/errors";
import { describeProblem } from "../app/problems";

export type LoadState = "idle" | "loading" | "ready" | "failed";

/** One-shot async value with an explicit retry entry point. */
export function useAsyncData<TValue>(loader: (signal: AbortSignal) => Promise<TValue>) {
  const data = shallowRef<TValue | null>(null);
  const state = ref<LoadState>("idle");
  const error = ref<unknown>(null);
  let controller: AbortController | null = null;
  let generation = 0;

  async function run(): Promise<void> {
    const currentGeneration = ++generation;
    controller?.abort();
    controller = new AbortController();
    state.value = "loading";
    error.value = null;
    try {
      const result = await loader(controller.signal);
      if (currentGeneration !== generation) return;
      data.value = result;
      state.value = "ready";
    } catch (caught) {
      if (caught instanceof AbortedError) return;
      if (currentGeneration !== generation) return;
      error.value = caught;
      state.value = "failed";
    }
  }

  function cancel(): void {
    generation++;
    controller?.abort();
    controller = null;
  }

  return {
    data,
    state,
    error,
    run,
    cancel,
    problem: computed(() => (error.value ? describeProblem(error.value) : null)),
    isLoading: computed(() => state.value === "loading"),
    isReady: computed(() => state.value === "ready"),
  };
}

export interface PagedSource<TItem> {
  items: TItem[];
  page: number;
  page_size: number;
  total: number;
}

/** Page navigation over an endpoint that returns `{items, page, page_size, total}`. */
export function usePagedList<TItem>(
  loader: (page: number, pageSize: number, signal: AbortSignal) => Promise<PagedSource<TItem>>,
  pageSize = 20,
) {
  const items = shallowRef<TItem[]>([]);
  const state = ref<LoadState>("idle");
  const error = ref<unknown>(null);
  const paging = reactive({ page: 1, pageSize, total: 0 });
  let controller: AbortController | null = null;
  let generation = 0;

  async function load(page = paging.page): Promise<void> {
    const currentGeneration = ++generation;
    controller?.abort();
    controller = new AbortController();
    state.value = "loading";
    error.value = null;
    try {
      const result = await loader(page, paging.pageSize, controller.signal);
      if (currentGeneration !== generation) return;
      items.value = result.items;
      paging.page = result.page;
      paging.pageSize = result.page_size;
      paging.total = result.total;
      state.value = "ready";
    } catch (caught) {
      if (caught instanceof AbortedError) return;
      if (currentGeneration !== generation) return;
      error.value = caught;
      state.value = "failed";
    }
  }

  const totalPages = computed(() => Math.max(1, Math.ceil(paging.total / paging.pageSize)));

  function next(): void {
    if (paging.page < totalPages.value) void load(paging.page + 1);
  }

  function previous(): void {
    if (paging.page > 1) void load(paging.page - 1);
  }

  function cancel(): void {
    generation++;
    controller?.abort();
    controller = null;
  }

  return {
    items,
    state,
    error,
    paging,
    totalPages,
    load,
    next,
    previous,
    cancel,
    problem: computed(() => (error.value ? describeProblem(error.value) : null)),
    isLoading: computed(() => state.value === "loading"),
    isEmpty: computed(() => state.value === "ready" && items.value.length === 0),
  };
}

/** Render an unknown error to a sentence without throwing on unexpected shapes. */
export function toMessage(error: unknown): string {
  return describeProblem(error).message;
}

/** Type guard used when a component needs a non-null value after load. */
export function unwrap<TValue>(value: Ref<TValue | null>): TValue | null {
  return value.value;
}
