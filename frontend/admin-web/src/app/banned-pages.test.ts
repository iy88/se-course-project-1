import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { BANNED_ROWS_PER_GROUP, lastBannedGroupPage, pageBannedGroup } from "./banned-pages";

describe("banned group pagination", () => {
  it("keeps every category on an independent page", () => {
    const rows = Array.from({ length: 12 }, (_, index) => ({
      id: index + 1,
      group: index < 7 ? ("dangerous_controlled" as const) : ("medicine_device" as const),
    }));

    const dangerous = pageBannedGroup(rows, "dangerous_controlled", 2);
    const medicine = pageBannedGroup(rows, "medicine_device", 1);

    assert.equal(dangerous.page, 2);
    assert.equal(dangerous.total, 7);
    assert.deepEqual(
      dangerous.rows.map((row) => row.id),
      [6, 7],
    );
    assert.equal(medicine.total, 5);
    assert.equal(medicine.rows.length, BANNED_ROWS_PER_GROUP);
  });

  it("clamps a deleted last page back to the remaining page", () => {
    assert.equal(lastBannedGroupPage(0), 1);
    assert.equal(lastBannedGroupPage(6), 2);
    assert.equal(
      pageBannedGroup(
        [
          { id: 1, group: "other" },
          { id: 2, group: "other" },
        ],
        "other",
        4,
      ).page,
      1,
    );
  });
});
