import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { CaseRelatedAccount } from "../api/cases";
import { dispositionTargets, resolveDispositionTarget } from "./disposition-targets";

const label = (account: CaseRelatedAccount) => account.display_name ?? account.account_id;

describe("case disposition targets", () => {
  it("automatically chooses the sole eligible account and excludes the reporter", () => {
    const choices = dispositionTargets(
      {
        related_accounts: [
          { account_id: "1", display_name: "Reporter", reporter: true, eligible: false },
          { account_id: "2", display_name: "Seller", reporter: false, eligible: true },
        ],
      },
      "account",
      label,
    );
    assert.deepEqual(choices, [{ id: "2", label: "Seller" }]);
    assert.equal(resolveDispositionTarget(choices, "")?.id, "2");
  });

  it("requires a valid selection among multiple products", () => {
    const choices = dispositionTargets(
      {
        disposition_targets: {
          target_type: "account",
          target_id: "2",
          products: [
            { id: "11", title: "Book" },
            { id: "12", title: "Lamp" },
          ],
        },
      },
      "product",
      label,
    );
    assert.deepEqual(choices, [
      { id: "11", label: "Book #11" },
      { id: "12", label: "Lamp #12" },
    ]);
    assert.equal(resolveDispositionTarget(choices, "12")?.id, "12");
    assert.equal(resolveDispositionTarget(choices, ""), undefined);
    assert.equal(resolveDispositionTarget(choices, "99"), undefined);
  });

  it("does not fall back to a reported product when the projection is explicitly empty", () => {
    const choices = dispositionTargets(
      {
        disposition_targets: { target_type: "product", target_id: "11", products: [] },
        reported_object: { target_type: "product", target_id: "11" },
      },
      "product",
      label,
    );
    assert.deepEqual(choices, []);
    assert.equal(resolveDispositionTarget(choices, "11"), undefined);
    assert.deepEqual(dispositionTargets(undefined, "account", label), []);
  });

  it("supports a legacy reported product and only offers a matching trade target", () => {
    assert.deepEqual(
      dispositionTargets(
        { reported_object: { target_type: "product", target_id: "11" } },
        "product",
        label,
      ),
      [{ id: "11", label: "商品 #11" }],
    );
    const detail = {
      disposition_targets: { target_type: "trade", target_id: "19", products: [] },
    };
    assert.deepEqual(dispositionTargets(detail, "trade", label), [{ id: "19", label: "交易 #19" }]);
    assert.deepEqual(dispositionTargets(detail, "comment", label), []);
  });
});
