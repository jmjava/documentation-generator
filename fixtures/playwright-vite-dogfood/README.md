# Playwright + Vite dogfood fixture

Tiny **Vite** app plus **@playwright/test** so this repository can run:

- `npx playwright test` / `npm run test:e2e`
- `docgen discover-tests` and `docgen discover-tests --merge-catalog` (from `docs/demos` with `discover_tests.roots` including this directory)

Specs live at the fixture root (`smoke.spec.ts`) so Playwright’s `--list --reporter=json` file paths line up with repo-relative paths for catalog fingerprints.

Not product code — only for local verification and docgen discovery against a realistic Node layout.

## Setup

```bash
cd fixtures/playwright-vite-dogfood
npm ci
npx playwright install chromium
```

## Run tests

```bash
npm run test:e2e
```

## docgen

From repository root, after `npm ci` here:

```bash
cd docs/demos
docgen --config docgen.yaml discover-tests
docgen --config docgen.yaml discover-tests --merge-catalog
```
