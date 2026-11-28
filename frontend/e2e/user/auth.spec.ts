import { expect, test, UUID, waitForPost } from "../support/fixtures";

test.describe("user authentication", () => {
  test("guards a deep link and signs in with the exact credentials", async ({ page, api }) => {
    const entryContext = page.waitForResponse(
      (response) => new URL(response.url()).pathname === "/api/v1/account/entry-context",
    );
    await page.goto("/products/1001");

    await expect(page).toHaveURL(
      (url) => url.pathname === "/login" && url.searchParams.get("redirect") === "/products/1001",
    );
    await entryContext;

    await page.getByLabel("邮箱").fill("buyer@campus.test");
    await page.getByLabel("密码").fill("CampusPass123!");
    const loginRequest = waitForPost(page, "/account/session");
    await page.getByRole("button", { name: "登录", exact: true }).click();
    const posted = await loginRequest;

    expect(posted.headers()["x-csrf-token"]).toBe(api.entryToken);
    expect(posted.headers()["idempotency-key"]).toMatch(UUID);
    expect(posted.postDataJSON()).toEqual({
      email: "buyer@campus.test",
      password: "CampusPass123!",
    });

    await expect(page).toHaveURL(/\/products\/1001$/);
    await expect(page.getByRole("heading", { name: "九成新机械键盘" })).toBeVisible();
    await expect(
      page.getByRole("link", { name: "我的" }).filter({ hasText: "林小满" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "发起购买请求" })).toBeEnabled();
  });

  test("reports invalid credentials without leaving the sign-in screen", async ({ page, api }) => {
    const entryContext = page.waitForResponse(
      (response) => new URL(response.url()).pathname === "/api/v1/account/entry-context",
    );
    await page.goto("/login");
    await entryContext;

    await page.getByLabel("邮箱").fill("buyer@campus.test");
    await page.getByLabel("密码").fill("wrong-password");
    const loginRequest = waitForPost(page, "/account/session");
    await page.getByRole("button", { name: "登录", exact: true }).click();
    const posted = await loginRequest;

    expect(posted.headers()["x-csrf-token"]).toBe(api.entryToken);
    await expect(page.getByRole("alert")).toHaveText("邮箱或密码不正确。");
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("heading", { name: "登录", exact: true })).toBeVisible();
  });

  test("confirms sign-out, clears the guarded view and keeps the next deep link signed out", async ({
    page,
    api,
  }) => {
    api.signedIn = true;

    await page.goto("/me");
    await expect(page.getByRole("heading", { name: "林小满", exact: true })).toBeVisible();
    const overviewRequests = api.requests.filter((item) => item === "GET /account/overview").length;

    await page.getByRole("button", { name: "退出登录" }).click();
    const dialog = page.getByRole("dialog", { name: "退出登录？" });
    await expect(dialog).toBeVisible();

    const logoutRequest = page.waitForRequest(
      (request) =>
        request.method() === "DELETE" &&
        new URL(request.url()).pathname === "/api/v1/account/session",
    );
    await dialog.getByRole("button", { name: "确认退出" }).click();
    await logoutRequest;

    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("heading", { name: "登录", exact: true })).toBeVisible();
    await expect(page.getByText("已退出登录。", { exact: true })).toBeVisible();

    await page.goto("/me");
    await expect(page).toHaveURL((url) => url.pathname === "/login");
    expect(api.requests.filter((item) => item === "GET /account/overview")).toHaveLength(
      overviewRequests,
    );
  });
});
