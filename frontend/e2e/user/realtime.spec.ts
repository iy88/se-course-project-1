import { expect, test } from "../support/fixtures";

test.describe("realtime recovery", () => {
  test("reconnects after a socket drop and applies the next notification event", async ({
    page,
    api,
  }) => {
    api.signedIn = true;

    await page.goto("/products/1001");
    await expect(page.getByRole("heading", { name: "九成新机械键盘" })).toBeVisible();
    await expect.poll(() => api.realtime.connections.length, { timeout: 8_000 }).toBeGreaterThan(0);
    const connectionsBeforeDrop = api.realtime.connections.length;
    expect(api.realtime.connections[connectionsBeforeDrop - 1]?.frames[0]).toMatchObject({
      type: "hello",
      protocol_version: 1,
      csrf_token: api.entryToken,
    });

    await api.realtime.disconnect(connectionsBeforeDrop - 1, 1011);
    await expect
      .poll(() => api.realtime.connections.length, { timeout: 8_000 })
      .toBeGreaterThan(connectionsBeforeDrop);
    await expect.poll(() => api.realtime.connections.at(-1)?.frames[0]?.type).toBe("hello");

    api.unreadCount = 9;
    api.realtime.emitEvent(1);
    await expect(page.getByText("未读9", { exact: true })).toBeVisible();
  });
});
