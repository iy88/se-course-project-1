/*
 * Own-business aggregation and platform capabilities.
 * Paths follow docs/design/detailed-design/interfaces/聚合与管理查询.md
 * (API-COM-QUERY-001—003) and the capabilities endpoint of the realtime work
 * package.
 */
import { request } from "./http";
import type { Capabilities, MyOverview, MyResourcePage, MyTodoPage, TodoKind } from "./contracts";

export function readOverview(signal?: AbortSignal): Promise<MyOverview> {
  return request<MyOverview>("GET", "/account/overview", { signal });
}

export function listMyTodos(
  query: { kind?: TodoKind; page?: number; page_size?: number },
  signal?: AbortSignal,
): Promise<MyTodoPage> {
  return request<MyTodoPage>("GET", "/account/todos", {
    query,
    signal,
  });
}

export function listMyResources(
  query: {
    kind: string;
    state?: string;
    role?: string;
    direction?: string;
    page?: number;
    page_size?: number;
  },
  signal?: AbortSignal,
): Promise<MyResourcePage> {
  return request<MyResourcePage>("GET", "/account/resources", {
    query,
    signal,
  });
}

export function readCapabilities(): Promise<Capabilities> {
  return request<Capabilities>("GET", "/capabilities");
}
