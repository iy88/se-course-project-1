import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { useAsyncData, usePagedList, type PagedSource } from "./async";

interface Deferred<T> {
  readonly promise: Promise<T>;
  resolve(value: T): void;
  reject(error: unknown): void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

describe("async state generations", () => {
  it("ignores an older one-shot success after a newer result is committed", async () => {
    const old = deferred<string>();
    const current = deferred<string>();
    const results = [old, current];
    let calls = 0;
    const state = useAsyncData(() => results[calls++].promise);

    const oldRun = state.run();
    const currentRun = state.run();
    current.resolve("new");
    await currentRun;
    assert.equal(state.data.value, "new");
    assert.equal(state.state.value, "ready");

    old.resolve("old");
    await oldRun;
    assert.equal(state.data.value, "new");
    assert.equal(state.state.value, "ready");
    assert.equal(state.error.value, null);
  });

  it("ignores an older one-shot error after a newer result is committed", async () => {
    const old = deferred<string>();
    const current = deferred<string>();
    const results = [old, current];
    let calls = 0;
    const state = useAsyncData(() => results[calls++].promise);

    const oldRun = state.run();
    const currentRun = state.run();
    current.resolve("new");
    await currentRun;

    old.reject(new Error("late old failure"));
    await oldRun;
    assert.equal(state.data.value, "new");
    assert.equal(state.state.value, "ready");
    assert.equal(state.error.value, null);
  });

  it("does not commit a late one-shot result after cancel", async () => {
    const result = deferred<string>();
    const state = useAsyncData(() => result.promise);

    const run = state.run();
    state.cancel();
    result.resolve("late");
    await run;
    assert.equal(state.data.value, null);
    assert.equal(state.error.value, null);
  });

  it("ignores an older paged success and its paging metadata", async () => {
    const old = deferred<PagedSource<string>>();
    const current = deferred<PagedSource<string>>();
    const results = [old, current];
    let calls = 0;
    const list = usePagedList(() => results[calls++].promise);

    const oldLoad = list.load(1);
    const currentLoad = list.load(2);
    current.resolve({ items: ["new"], page: 2, page_size: 20, total: 21 });
    await currentLoad;
    assert.deepEqual(list.items.value, ["new"]);
    assert.equal(list.paging.page, 2);
    assert.equal(list.paging.total, 21);
    assert.equal(list.state.value, "ready");

    old.resolve({ items: ["old"], page: 1, page_size: 20, total: 1 });
    await oldLoad;
    assert.deepEqual(list.items.value, ["new"]);
    assert.equal(list.paging.page, 2);
    assert.equal(list.paging.total, 21);
    assert.equal(list.state.value, "ready");
    assert.equal(list.error.value, null);
  });

  it("ignores an older paged error after a newer result is committed", async () => {
    const old = deferred<PagedSource<string>>();
    const current = deferred<PagedSource<string>>();
    const results = [old, current];
    let calls = 0;
    const list = usePagedList(() => results[calls++].promise);

    const oldLoad = list.load(1);
    const currentLoad = list.load(2);
    current.resolve({ items: ["new"], page: 2, page_size: 20, total: 21 });
    await currentLoad;

    old.reject(new Error("late old page failure"));
    await oldLoad;
    assert.deepEqual(list.items.value, ["new"]);
    assert.equal(list.paging.page, 2);
    assert.equal(list.state.value, "ready");
    assert.equal(list.error.value, null);
  });

  it("does not commit a late paged result after cancel", async () => {
    const result = deferred<PagedSource<string>>();
    const list = usePagedList(() => result.promise);

    const load = list.load(1);
    list.cancel();
    result.resolve({ items: ["late"], page: 1, page_size: 20, total: 1 });
    await load;
    assert.deepEqual(list.items.value, []);
    assert.equal(list.error.value, null);
  });
});
