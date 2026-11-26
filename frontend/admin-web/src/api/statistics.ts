import type { components } from "../../../shared/api-types";
import { request } from "./http";

export type ManagementStatistics = components["schemas"]["ManagementStatistics"];
export type StatisticsSelection =
  | { time_scope: "all" }
  | { time_scope: "range"; start_at: string; end_at: string };

export function readStatistics(
  selection: StatisticsSelection,
  signal?: AbortSignal,
): Promise<ManagementStatistics> {
  return request("GET", "/management/statistics", { query: selection, signal });
}
