# Milestone — Multi-host AI and `--repo` hardening

**Goal:** Same `docgen` CLI in Cursor Cloud, local Cursor, and Claude Code, without vendoring the library into a consumer `src/`. Fail closed on bad keys, empty model replies, and clone-cache mistakes.

**Branch / PR:** `cursor/senior-python-ai-review-2ccd` (follow-up to #75).

## Shipped

- [x] Host-agnostic keys: `CURSOR_API_KEY` then `OPENAI_API_KEY`; skip Cloud `crsr_` proxies
- [x] Anthropic chat when that is the only usable key; TTS/images still need OpenAI or Grok
- [x] `AIError` + typed `ProviderName`; `docgen ai-status`
- [x] Clone token off `git` argv; append `GIT_CONFIG_*` instead of clobbering count
- [x] `find_bundle_yaml` prunes `node_modules` / `.venv` / `recordings`
- [x] Cache dirs are `owner-repo`; reject a cache whose `origin` does not match
- [x] `--repo docs/demos` is a missing local path when `docs/` exists, not GitHub shorthand
- [x] Empty OpenAI/Grok chat raises (same as Anthropic); close HTTP bodies before 429/5xx retry
- [x] Cached clone fetches **`origin HEAD`** then `reset --hard FETCH_HEAD`
- [x] `timestamps extract_all` does not write `timing.json` as `{}` when there are no `*.mp3`
- [x] urllib **connection** errors (`URLError`) retry with the same backoff as 5xx
- [x] OpenAI/Grok **chat** uses `call_with_rate_limit_retries`
- [x] Pasted GitHub **page** URLs (`/tree/…`, `/blob/…`) normalize to `owner/repo.git`
- [x] Image CDN `fetch_url_bytes` retries 5xx / connection errors
- [x] Whisper STT rate-limit retries; whisper engine fail-fast when the provider has no STT
- [x] Wizard `/api/session` exposes provider + key present (not the secret); status bar shows it
- [x] CLI copy says “chat”, not “OpenAI”, for yaml-generate / scene-spec / rebuild

## Deferred (not this library’s job)

- Anthropic TTS/images (no API)
- urllib → httpx
- Pushing consumer bundles (`slm-setup`) from this repo
- Archived roadmaps (slides, i18n, Playwright, Embabel) — see `archive/`
