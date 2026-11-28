import { adminAccount } from "../support/mock-api";
import { expect, test, UUID, waitForPost } from "../support/fixtures";

test.describe("administration permissions and review", () => {
  test("shows the permission gate to a signed-in non-manager", async ({ page, api }) => {
    api.signedIn = true;

    await page.goto("/");

    await expect(page.getByRole("heading", { name: "需要平台管理权限" })).toBeVisible();
    await expect(page.getByText("buyer@campus.test", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "退出登录" })).toBeVisible();
    expect(api.requests).not.toContain("GET /management/todos");
  });

  test("claims a queued review, validates the form and submits the decision payload", async ({
    page,
    api,
  }) => {
    api.account = adminAccount();

    await page.goto("/cases?ownership=unclaimed&kind=product_review");
    await expect(page.getByRole("heading", { name: "管理员登录" })).toBeVisible();

    await page.getByLabel("邮箱").fill("admin@campus.test");
    await page.getByLabel("密码").fill("AdminPass123!");
    const loginRequest = waitForPost(page, "/account/session");
    await page.getByRole("button", { name: "登录管理端" }).click();
    const login = await loginRequest;

    expect(login.headers()["x-csrf-token"]).toBe(api.entryToken);
    expect(login.postDataJSON()).toEqual({
      email: "admin@campus.test",
      password: "AdminPass123!",
    });

    await expect(page.getByRole("heading", { name: "事项工作台" })).toBeVisible();
    await expect(page.getByText("九成新机械键盘", { exact: true })).toBeVisible();

    const claimRequest = waitForPost(page, "/admin/cases/7001/claim");
    await page.getByRole("button", { name: "认领", exact: true }).click();
    const claim = await claimRequest;

    expect(claim.postData()).toBeNull();
    expect(claim.headers()["idempotency-key"]).toMatch(UUID);
    await expect(page).toHaveURL(/\/reviews\/9001$/);
    await expect(page.getByRole("heading", { name: "审核商品 #1001" })).toBeVisible();
    await expect(page.getByText("审核 #9001", { exact: true })).toBeVisible();

    await page.getByRole("radio", { name: "不通过", exact: true }).check();
    await page.getByRole("button", { name: "提交审核结论" }).click();
    await expect(page.getByRole("alert")).toHaveText("不通过时必须填写审核原因。");
    expect(api.requests).not.toContain("POST /admin/product-reviews/9001/decision");

    await page.getByLabel("审核原因").fill("商品描述含联系方式");
    await page.getByRole("button", { name: "提交审核结论" }).click();
    await expect(page.getByRole("alert")).toHaveText("存在待审核的分类申请，请选择批准或不批准。");
    expect(api.requests).not.toContain("POST /admin/product-reviews/9001/decision");

    await page.getByRole("radio", { name: "不批准", exact: true }).check();
    await page.getByLabel("分类申请理由").fill("请改用已有分类");
    await page.getByRole("checkbox", { name: /代写作业/ }).check();

    const decisionRequest = waitForPost(page, "/admin/product-reviews/9001/decision");
    await page.getByRole("button", { name: "提交审核结论" }).click();
    const decision = await decisionRequest;

    expect(decision.headers()["x-csrf-token"]).toBe(api.entryToken);
    expect(decision.headers()["idempotency-key"]).toMatch(UUID);
    expect(decision.postDataJSON()).toEqual({
      decision: "rejected",
      reason: "商品描述含联系方式",
      banned_item_ids: ["banned-1"],
      category_application_decision: "rejected",
      category_application_reason: "请改用已有分类",
    });

    await expect(page.getByText("审核未通过。", { exact: true })).toBeVisible();
    await expect(page.getByText("未通过", { exact: true })).toBeVisible();
    await expect(page.getByText("商品描述含联系方式", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "提交审核结论" })).toHaveCount(0);
  });
});
