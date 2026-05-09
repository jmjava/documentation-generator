import { expect, test } from "@playwright/test";

test("compile lesson flow", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("heading")).toContainText("Course Builder");

  await page.getByTestId("topic").pressSequentially("Async iterators", {
    delay: 150,
  });
  await page.getByTestId("compile").click();

  await expect(page.getByTestId("output")).toContainText(
    "Compiled lesson: Async iterators",
  );
});
