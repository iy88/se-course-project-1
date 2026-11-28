import { expect, test, waitForPost } from "../support/fixtures";

test.describe("frontend resilience", () => {
  test("keeps the newest search result when an older response finishes last", async ({
    page,
    api,
  }) => {
    api.signedIn = true;
    const oldResponse = api.holdNext(
      "GET /products",
      (url) => url.searchParams.get("keyword") === "old",
    );

    await page.goto("/search?q=old");
    await oldResponse.reached;

    await page.getByLabel("搜索商品").fill("new");
    await page.getByRole("button", { name: "搜索", exact: true }).click();

    await expect(page.getByRole("heading", { name: "新搜索结果" })).toBeVisible();
    oldResponse.release();
    await oldResponse.settled;

    await expect(page.getByRole("heading", { name: "新搜索结果" })).toBeVisible();
    await expect(page.getByText("旧搜索结果", { exact: true })).toHaveCount(0);
  });

  test("coalesces repeated purchase clicks while the first request is pending", async ({
    page,
    api,
  }) => {
    api.signedIn = true;
    const heldPurchase = api.holdNext("POST /products/1001/purchase-requests");

    await page.goto("/products/1001");
    await page.getByRole("button", { name: "发起购买请求" }).click();
    await page
      .getByRole("dialog", { name: "发起购买请求" })
      .getByLabel("给卖方的说明（可选）")
      .fill("只提交一次");

    const confirm = page
      .getByRole("dialog", { name: "发起购买请求" })
      .getByRole("button", { name: "提交请求" });
    await confirm.click();
    await heldPurchase.reached;
    await expect(page.getByText("正在提交…", { exact: true })).toBeVisible();

    await confirm.click();
    expect(
      api.requests.filter((item) => item === "POST /products/1001/purchase-requests"),
    ).toHaveLength(1);

    heldPurchase.release();
    await expect(page).toHaveURL(/\/trades\/2001$/);
    expect(
      api.requests.filter((item) => item === "POST /products/1001/purchase-requests"),
    ).toHaveLength(1);
  });

  test("retries a failed purchase with the same idempotency key", async ({ page, api }) => {
    api.signedIn = true;
    api.failNext("POST /products/1001/purchase-requests");

    await page.goto("/products/1001");
    await page.getByRole("button", { name: "发起购买请求" }).click();
    const dialog = page.getByRole("dialog", { name: "发起购买请求" });
    await dialog.getByLabel("给卖方的说明（可选）").fill("网络恢复后重试");

    const firstRequest = waitForPost(page, "/products/1001/purchase-requests");
    await dialog.getByRole("button", { name: "提交请求" }).click();
    const first = await firstRequest;

    await expect(dialog.getByRole("alert")).toHaveText("网络不可用，请检查连接后重试。");
    await expect(page.getByText("网络连接暂不可用，请检查网络后重试。")).toBeVisible();

    const retryRequest = waitForPost(page, "/products/1001/purchase-requests");
    await dialog.getByRole("button", { name: "提交请求" }).click();
    const retry = await retryRequest;

    expect(retry.headers()["idempotency-key"]).toBe(first.headers()["idempotency-key"]);
    await expect(page).toHaveURL(/\/trades\/2001$/);
    expect(
      api.requests.filter((item) => item === "POST /products/1001/purchase-requests"),
    ).toHaveLength(2);
  });
});
