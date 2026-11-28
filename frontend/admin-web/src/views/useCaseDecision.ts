/* Page-local decision draft that must survive detail reloads, load failures, and permission changes. */
import { computed, reactive, type Ref } from "vue";
import type {
  CaseDecision,
  CaseEnforcementInput,
  CaseManagementWrites,
  CaseRelatedAccount,
  ManagementCaseDetail,
} from "../api/cases";
import { dispositionTargets, resolveDispositionTarget } from "../app/disposition-targets";

export interface DecisionInstruction {
  id: number;
  option: number;
  targetId: string;
  expected: string;
}

export interface DecisionDraft {
  decisionKind: CaseDecision;
  decisionReason: string;
  basis: string[];
  instructions: DecisionInstruction[];
}

export type EnforcementTarget = "account" | "product" | "comment" | "evaluation" | "trade";

export interface EnforcementOption {
  action: string;
  target: EnforcementTarget;
  label: string;
}

export interface DispositionChoice {
  id: string;
  label: string;
}

export type DecisionWriteResult = { body: CaseManagementWrites["decisions"] } | { error: string };

export function useCaseDecision(
  detail: Ref<ManagementCaseDetail | undefined>,
  enforcementOptions: readonly EnforcementOption[],
  accountLabel: (account: CaseRelatedAccount) => string,
) {
  const draft = reactive<DecisionDraft>({
    decisionKind: "no_action",
    decisionReason: "",
    basis: [],
    instructions: [],
  });
  let instructionId = 0;

  const dispositionChoices = computed<DispositionChoice[][]>(() =>
    enforcementOptions.map(({ target }) => dispositionTargets(detail.value, target, accountLabel)),
  );

  function addInstruction(): void {
    const option = dispositionChoices.value.findIndex((choices) => choices.length);
    if (option >= 0) {
      draft.instructions.push({
        id: ++instructionId,
        option,
        targetId: "",
        expected: "terminated",
      });
    }
  }

  function removeInstruction(id: number): void {
    draft.instructions = draft.instructions.filter((item) => item.id !== id);
  }

  function buildDecisionWrite(): DecisionWriteResult {
    const enforcements: CaseEnforcementInput[] = [];
    if (draft.decisionKind === "violation") {
      for (const entry of draft.instructions) {
        const option = enforcementOptions[entry.option];
        const choices = dispositionChoices.value[entry.option];
        const target = resolveDispositionTarget(choices, entry.targetId);
        if (!target) {
          return { error: "请选择有效的处置对象。" };
        }
        enforcements.push({
          action: option.action,
          target_type: option.target,
          target_id: target.id,
          expected_result: option.action === "adjust_trade_status" ? entry.expected : undefined,
        });
      }
    }
    return {
      body: {
        decision_kind: draft.decisionKind,
        reason: draft.decisionReason.trim(),
        basis_refs: draft.basis,
        enforcements,
      },
    };
  }

  return { draft, dispositionChoices, addInstruction, removeInstruction, buildDecisionWrite };
}
