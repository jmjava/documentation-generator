# Milestone — Multi-host AI and `--repo` hardening

**Goal:** Same `docgen` CLI in Cursor Cloud, local Cursor, and Claude Code, without vendoring the library into a consumer `src/`. Fail closed on bad keys, empty model replies, and clone-cache mistakes.

**Branch / PR:** `cursor/senior-python-ai-review-2ccd` (follow-up to #75).

## Shipped (prior commits on this line)

- [x] Host-agnostic keys: `CURSOR_API_KEY` then `OPENAI_API_KEY`; skip Cloud `crsr_` proxies
- [x] Anthropic chat when that is the only usable key; TTS/images still need OpenAI or Grok
- [x] `AIError` + typed `ProviderName`; `docgen ai-status`
- [x] Clone token off `git` argv; append `GIT_CONFIG_*` instead of clobbering count
- [x] `find_bundle_yaml` prunes `node_modules` / `.venv` / `recordings`
- [x] Cache dirs are `owner-repo`; reject a cache whose `origin` does not match
- [x] `--repo docs/demos` is a missing local path when `docs/` exists, not GitHub shorthand
- [x] Empty OpenAI/Grok chat raises (same as Anthropic); close HTTP bodies before 429/5xx retry

## Open (this round)

- [ ] Cached clone `git fetch` must update **remote HEAD**, then `reset --hard FETCH_HEAD`. Bare `git fetch origin` leaves `FETCH_HEAD` on an arbitrary last ref, so the working tree can jump to the wrong branch.
- [ ] `timestamps extract_all` must not write `timing.json` as `{}` when `audio/` exists but has no `*.mp3` (`generate-all --skip-tts` / first-run wipe).
- [ ] urllib **connection** errors (`URLError`) retry with the same backoff as 5xx.
- [ ] OpenAI/Grok **chat** uses `call_with_rate_limit_retries` (TTS and images already do).

## Out of scope

- Anthropic TTS/images (no API)
- Switching urllib to httpx
- Pushing consumer bundles (`slm-setup`) from this library repo
