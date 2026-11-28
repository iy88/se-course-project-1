/* Page-local trade history request state for the case detail view. */
import { ref } from "vue";
import { readCaseTradeHistory, type CaseTradeHistory } from "../api/cases";
import { AbortedError } from "../api/errors";

export function useCaseTradeHistory(getCaseId: () => string) {
  const tradeHistory = ref<CaseTradeHistory>();
  const tradeHistoryLoading = ref(false);
  const tradeHistoryError = ref<unknown>();
  let tradeHistoryRequest: AbortController | undefined;

  async function loadTradeHistory(): Promise<void> {
    const controller = new AbortController();
    tradeHistoryRequest = controller;
    tradeHistoryLoading.value = true;
    tradeHistoryError.value = undefined;
    try {
      tradeHistory.value = await readCaseTradeHistory(getCaseId(), controller.signal);
    } catch (caught) {
      if (!(caught instanceof AbortedError)) tradeHistoryError.value = caught;
    } finally {
      tradeHistoryLoading.value = false;
    }
  }

  function abortTradeHistory(): void {
    tradeHistoryRequest?.abort();
  }

  return {
    tradeHistory,
    tradeHistoryLoading,
    tradeHistoryError,
    loadTradeHistory,
    abortTradeHistory,
  };
}
