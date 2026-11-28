import { sellerAccount } from "../support/mock-api";
import { expect, test, UUID, waitForPost } from "../support/fixtures";

test.describe("product purchase request", () => {
  test("sends the rendered product version and opens the created trade", async ({ page, api }) => {
    api.signedIn = true;

    await page.goto("/products/1001");
    await expect(page.getByRole("heading", { name: "九成新机械键盘" })).toBeVisible();
    await expect(page.getByRole("button", { name: "发起购买请求" })).toBeEnabled();

    await page.getByRole("button", { name: "发起购买请求" }).click();
    const dialog = page.getByRole("dialog", { name: "发起购买请求" });
    await expect(dialog).toBeVisible();
    await dialog.getByLabel("给卖方的说明（可选）").fill("今晚六点自提");

    const purchaseRequest = waitForPost(page, "/products/1001/purchase-requests");
    await dialog.getByRole("button", { name: "提交请求" }).click();
    const posted = await purchaseRequest;

    expect(posted.postDataJSON()).toEqual({
      note: "今晚六点自提",
      expected_product_version: 4,
    });
    expect(posted.headers()["idempotency-key"]).toMatch(UUID);

    await expect(page).toHaveURL(/\/trades\/2001$/);
    await expect(page.getByRole("heading", { name: "九成新机械键盘" })).toBeVisible();
    await expect(page.getByRole("paragraph").filter({ hasText: /^待接受$/ })).toBeVisible();
    await expect(page.getByText(/今晚六点自提/)).toBeVisible();
    await expect(page.getByRole("heading", { name: "购买请求", exact: true })).toBeVisible();
  });

  test("publishes a product with its selected category and opens the review preview", async ({
    page,
    api,
  }) => {
    api.account = sellerAccount();
    api.signedIn = true;

    await page.goto("/products/new");
    await expect(page.getByRole("heading", { name: "发布商品" })).toBeVisible();

    await page.getByLabel("标题").fill("折叠台灯");
    await page.getByLabel("描述").fill("亮度三档可调，宿舍桌面使用。");
    await page.getByLabel("价格（元）").fill("35.50");
    await page.getByRole("button", { name: "数码", exact: true }).click();

    const publishRequest = waitForPost(page, "/products");
    await page.getByRole("button", { name: "提交审核" }).click();
    const posted = await publishRequest;

    expect(posted.headers()["idempotency-key"]).toMatch(UUID);
    expect(posted.postDataJSON()).toEqual({
      title: "折叠台灯",
      description: "亮度三档可调，宿舍桌面使用。",
      price_cents: 3550,
      category_ids: ["10"],
      image_file_ids: [],
    });

    await expect(page).toHaveURL(/\/products\/1002$/);
    await expect(page.getByRole("heading", { name: "折叠台灯" })).toBeVisible();
    await expect(
      page.getByText("商品已提交审核，通过后会公开展示。", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("region", { name: "折叠台灯" }).getByText("待审核", { exact: true }),
    ).toBeVisible();
  });
});
