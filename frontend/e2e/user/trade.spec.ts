import { sellerAccount } from "../support/mock-api";
import { expect, test, UUID, waitForPost } from "../support/fixtures";

test.describe("trade acceptance", () => {
  test("accepts a pending request with its version and reveals agreement actions", async ({
    page,
    api,
  }) => {
    api.account = sellerAccount();
    api.signedIn = true;

    await page.goto("/trades/2001");
    await expect(page.getByRole("heading", { name: "九成新机械键盘" })).toBeVisible();
    await expect(page.getByRole("paragraph").filter({ hasText: /^待接受$/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "接受请求" })).toBeVisible();
    await expect(page.getByRole("button", { name: "拒绝请求" })).toBeVisible();

    const acceptRequest = waitForPost(page, "/trades/2001/accept");
    await page.getByRole("button", { name: "接受请求" }).click();
    const posted = await acceptRequest;

    expect(posted.postDataJSON()).toEqual({ expected_version: 3 });
    expect(posted.headers()["idempotency-key"]).toMatch(UUID);

    await expect(page.getByText("交易中", { exact: true })).toBeVisible();
    await expect(page.getByText("等待约定生效", { exact: true })).toBeVisible();
    await expect(page.getByText("已接受请求，请提出交付与支付约定。")).toBeVisible();
    await expect(page.getByRole("button", { name: "提出约定" })).toBeVisible();
    await expect(page.getByRole("button", { name: "接受请求" })).toHaveCount(0);
  });
});
