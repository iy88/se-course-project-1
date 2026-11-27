import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { categoryFilterOptions } from "./category-filters";

describe("category filter options", () => {
  it("keeps a main name and all aliases on one category id", () => {
    const [option] = categoryFilterOptions([
      {
        id: "7",
        main_name: "教材资料",
        aliases: ["课本", "教科书"],
      },
    ]);

    assert.deepEqual(option, {
      id: "7",
      label: "教材资料（别名：课本、教科书）",
      aliases: ["课本", "教科书"],
    });
  });

  it("removes blank, duplicate and main-name aliases", () => {
    const [option] = categoryFilterOptions([
      {
        id: "7",
        main_name: "教材资料",
        aliases: [" 课本 ", "", "课本", "教材资料"],
      },
    ]);

    assert.deepEqual(option.aliases, ["课本"]);
    assert.equal(option.label, "教材资料（别名：课本）");
  });

  it("leaves a category without aliases as one unchanged option", () => {
    assert.deepEqual(categoryFilterOptions([{ id: "8", main_name: "数码", aliases: [] }]), [
      { id: "8", label: "数码", aliases: [] },
    ]);
  });
});
