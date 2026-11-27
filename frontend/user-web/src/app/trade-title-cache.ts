import type { ConversationBranch } from "../api/contracts";

type TitleCache = Map<string, string | null>;
type TitleFetcher = (id: string, signal: AbortSignal) => Promise<string | null>;

function tradeId(branch: ConversationBranch): string | undefined {
  if (branch.conversation_kind !== "trade") return;
  const source = branch.source_ref;
  if (typeof source === "string") return /^trade:([0-9]+)$/.exec(source)?.[1];
  return source?.resource_type === "trade" ? source.resource_id : undefined;
}

export function cachedTradeTitle(
  cache: TitleCache,
  accountId: string | null,
  branch: ConversationBranch,
): string | null | undefined {
  const id = tradeId(branch);
  if (!accountId || !id) return;
  return cache.get(`${accountId}:${id}`);
}

/** Null reserves an in-flight key; failed reads remove it so a later refresh can retry. */
export async function loadTradeTitles(
  cache: TitleCache,
  accountId: string | null,
  branches: ConversationBranch[],
  fetchTitle: TitleFetcher,
  signal: AbortSignal,
): Promise<void> {
  if (!accountId || signal.aborted) return;
  const requests: Promise<void>[] = [];
  for (const branch of branches) {
    const id = tradeId(branch);
    if (!id) continue;
    const key = `${accountId}:${id}`;
    if (cache.has(key)) continue;
    cache.set(key, null);
    requests.push(
      (async () => {
        try {
          const title = await fetchTitle(id, signal);
          if (signal.aborted) cache.delete(key);
          else cache.set(key, title);
        } catch {
          cache.delete(key);
        }
      })(),
    );
  }
  await Promise.all(requests);
}
