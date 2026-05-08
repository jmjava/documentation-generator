import { expect, test } from "@playwright/test";

test("home page shows dogfood heading", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("heading")).toContainText("dogfood");
});
