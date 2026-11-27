import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ConversationBranch } from "../api/contracts";
import { cachedTradeTitle, loadTradeTitles } from "./trade-title-cache";

function trade(source_ref: ConversationBranch["source_ref"]): ConversationBranch {
  return { conversation_kind: "trade", conversation_id: "1", source_ref, unread_count: 0 };
}

describe("trade conversation title cache", () => {
  it("deduplicates in-flight and cached reads, including both reference formats", async () => {
    const cache = new Map<string, string | null>();
    const signal = new AbortController().signal;
    const branch = trade("trade:19");
    const duplicate = trade({ resource_type: "trade", resource_id: "19" });
    const chat = { ...branch, conversation_kind: "chat" as const };
    const invalid = trade("product:19");
    let calls = 0;
    const fetchTitle = async (id: string, receivedSignal: AbortSignal) => {
      calls++;
      assert.equal(id, "19");
      assert.equal(receivedSignal, signal);
      return "Book";
    };
    const first = loadTradeTitles(
      cache,
      "1",
      [branch, duplicate, chat, invalid],
      fetchTitle,
      signal,
    );
    const second = loadTradeTitles(cache, "1", [branch], fetchTitle, signal);
    await Promise.all([first, second]);
    await loadTradeTitles(cache, "1", [branch], fetchTitle, signal);
    assert.equal(calls, 1);
    assert.equal(cachedTradeTitle(cache, "1", duplicate), "Book");
    assert.equal(cachedTradeTitle(cache, "1", chat), undefined);
    assert.equal(cachedTradeTitle(cache, null, branch), undefined);
  });

  it("isolates cached titles by account and avoids reads while logged out", async () => {
    const cache = new Map<string, string | null>();
    const signal = new AbortController().signal;
    const branch = trade("trade:19");
    let calls = 0;
    const fetchTitle = async () => `Title ${++calls}`;
    await loadTradeTitles(cache, "1", [branch], fetchTitle, signal);
    await loadTradeTitles(cache, null, [branch], fetchTitle, signal);
    assert.equal(cachedTradeTitle(cache, "2", branch), undefined);
    await loadTradeTitles(cache, "2", [branch], fetchTitle, signal);
    assert.equal(calls, 2);
    assert.equal(cachedTradeTitle(cache, "1", branch), "Title 1");
    assert.equal(cachedTradeTitle(cache, "2", branch), "Title 2");
  });

  it("falls back after a failed read and retries on the next refresh", async () => {
    const cache = new Map<string, string | null>();
    const signal = new AbortController().signal;
    const branch = trade("trade:19");
    await loadTradeTitles(
      cache,
      "1",
      [branch],
      async () => {
        throw new Error("unavailable");
      },
      signal,
    );
    assert.equal(cachedTradeTitle(cache, "1", branch), undefined);
    await loadTradeTitles(cache, "1", [branch], async () => "Recovered", signal);
    assert.equal(cachedTradeTitle(cache, "1", branch), "Recovered");
  });

  it("does not retain a response after cancellation", async () => {
    const cache = new Map<string, string | null>();
    const controller = new AbortController();
    const branch = trade("trade:19");
    const pending = loadTradeTitles(cache, "1", [branch], async () => "Book", controller.signal);
    controller.abort();
    await pending;
    assert.equal(cachedTradeTitle(cache, "1", branch), undefined);
  });
});
