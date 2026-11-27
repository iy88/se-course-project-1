import type { CategoryView } from "../api/contracts";

export interface CategoryFilterOption {
  id: string;
  label: string;
  aliases: string[];
}

/**
 * Projects a category into one filter option. Names and aliases describe the same
 * stable category id, so aliases must never create additional selectable entries.
 */
export function categoryFilterOptions(
  categories: readonly Pick<CategoryView, "id" | "main_name" | "aliases">[],
): CategoryFilterOption[] {
  return categories.map((category) => {
    const mainName = category.main_name.trim();
    const aliases = [
      ...new Set(
        category.aliases
          .map((alias) => alias.trim())
          .filter((alias) => alias !== "" && alias !== mainName),
      ),
    ];
    return {
      id: category.id,
      label: aliases.length === 0 ? mainName : `${mainName}（别名：${aliases.join("、")}）`,
      aliases,
    };
  });
}
