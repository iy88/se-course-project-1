import { expect, test } from "../support/fixtures";

test.describe("PWA offline shell", () => {
  test("loads the cached application offline and reports recovery", async ({ page, api }) => {
    api.signedIn = true;

    await page.goto("/");
    await expect(page.getByRole("heading", { name: "九成新机械键盘" })).toBeVisible();
    await page.evaluate(async () => {
      await navigator.serviceWorker.ready;
    });
    await page.reload();
    await page.waitForFunction(() => navigator.serviceWorker.controller !== null);
    await expect(page.getByRole("heading", { name: "九成新机械键盘" })).toBeVisible();

    await page.context().setOffline(true);
    await page.reload();

    await expect(page.getByText("校园二手交易", { exact: true }).first()).toBeVisible();
    await expect(
      page.getByText("网络已断开，当前显示已缓存的页面。请检查网络后重试。"),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "九成新机械键盘" })).toBeVisible();

    await page.context().setOffline(false);
    await expect(page.getByText("网络已恢复。可重试刚才的操作。")).toBeVisible();
  });
});
