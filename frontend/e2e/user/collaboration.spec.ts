import { sellerAccount } from "../support/mock-api";
import { expect, test } from "../support/fixtures";

test.describe("multi-session collaboration", () => {
  test("lets a seller accept in one browser context and a buyer refresh from another", async ({
    browser,
    page,
    api,
    baseURL,
  }) => {
    if (!baseURL) throw new Error("The user-web project must provide a baseURL");
    api.signedIn = true;

    const sellerContext = await browser.newContext();
    const sellerPage = await sellerContext.newPage();
    await api.installAs(sellerPage, baseURL, {
      account: sellerAccount(),
      signedIn: true,
    });

    try {
      await page.goto("/trades/2001");
      await sellerPage.goto("/trades/2001");

      await expect(page.getByRole("button", { name: "撤回请求" })).toBeVisible();
      await expect(page.getByRole("button", { name: "接受请求" })).toHaveCount(0);
      await expect(sellerPage.getByRole("button", { name: "接受请求" })).toBeVisible();

      await sellerPage.getByRole("button", { name: "接受请求" }).click();
      await expect(sellerPage.getByText("交易中", { exact: true })).toBeVisible();
      await expect(sellerPage.getByText("等待约定生效", { exact: true })).toBeVisible();
      await expect(page.getByRole("paragraph").filter({ hasText: /^待接受$/ })).toBeVisible();

      await page.reload();
      await expect(page.getByText("交易中", { exact: true })).toBeVisible();
      await expect(page.getByText("等待约定生效", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "撤回请求" })).toHaveCount(0);
    } finally {
      await sellerContext.close();
    }
  });
});
