/* Shared case workbench query (API-COM-QUERY-004). */
import { request } from "./http";
import type { ManagementTodoPage, TodoKind, WorkbenchOwnership } from "./contracts";

export interface CaseQueueQuery {
  ownership: WorkbenchOwnership;
  kind: TodoKind;
  keyword?: string;
  page: number;
  page_size: number;
}

/** Four ownership scopes, type filter, keyword and paging are all applied before paging. */
export function listCaseQueue(
  query: CaseQueueQuery,
  signal?: AbortSignal,
): Promise<ManagementTodoPage> {
  return request<ManagementTodoPage>("GET", "/management/todos", {
    query: {
      ownership: query.ownership,
      kind: query.kind,
      keyword: query.keyword?.trim() || undefined,
      page: query.page,
      page_size: query.page_size,
    },
    signal,
  });
}
