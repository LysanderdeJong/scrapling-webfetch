---
name: web-fetch
description: >-
  Fetch rendered web pages with the local webfetch CLI. Use when a page needs
  JavaScript rendering, CSS-selector extraction, bot/Cloudflare handling, or when
  built-in fetch output is empty, blocked, or placeholder-only.
---

# web-fetch

Use `webfetch`, the Scrapling-based one-shot CLI. It returns JSON:

```json
{"status": 200, "url": "https://example.com/", "content": ["..."]}
```

## Decision Ladder

1. Static/simple page: `webfetch get URL --extraction-type markdown`
2. JavaScript-rendered page: `webfetch fetch URL --extraction-type markdown`
3. Bot protection or Cloudflare: `webfetch stealthy-fetch URL --extraction-type markdown`

Stay explicit. Do not hide retries behind auto-escalation. If output is empty,
blocked, spinner-only, or consent-shell-only, retry with the next ladder step or
the recovery options below.

## Recovery Options

Consent shell or hydrated content missing:

```bash
webfetch fetch URL --network-idle --wait 3000 --extraction-type markdown
```

Known late element:

```bash
webfetch fetch URL --wait-selector '#content' --network-idle --extraction-type markdown
```

Hard protection:

```bash
webfetch stealthy-fetch URL --solve-cloudflare --extraction-type markdown
```

One-shot stealth blocked but a normal browser session should work:

```bash
webfetch stealthy-fetch URL \
  --warmup-url https://marketplace.example/ \
  --real-chrome \
  --no-browser-flags \
  --locale nl-NL \
  --timezone-id Europe/Amsterdam \
  --network-idle \
  --wait 2500 \
  --no-google-search \
  --block-webrtc \
  --hide-canvas \
  --no-block-ads \
  --extraction-type text
```

Consent-gated site setup:

```bash
webfetch stealthy-fetch URL \
  --user-data-dir .webfetch-profile \
  --headful \
  --real-chrome \
  --no-browser-flags \
  --locale nl-NL \
  --timezone-id Europe/Amsterdam \
  --network-idle \
  --wait 60000 \
  --extraction-type text
```

## Selectors

Use `--css-selector` after the page is reachable to reduce tokens. Start broad,
then narrow.

Broad content selectors:

```bash
webfetch fetch URL --css-selector 'main, [role="main"], article' --extraction-type markdown
```

Repeated product/result selectors:

```bash
webfetch fetch URL --css-selector '.product, .product-card, [data-testid*="product"], [class*="product"]' --extraction-type text
```

If selector output is empty, retry once without the selector before escalating;
the selector may be wrong even when rendering worked. Prefer semantic selectors
and `data-testid` over generated class names.

## Options To Remember

- `--extraction-type markdown|html|text` — default `markdown`.
- `--main-content-only / --no-main-content-only` — default on; keeps prompt-injection cleanup.
- `--network-idle`, `--wait <ms>`, `--wait-selector <css>` — hydration recovery.
- `--headless / --headful` — browser commands default to headless; use headful for manual consent/login setup.
- `--block-ads / --no-block-ads` — browser commands default to Scrapling ad/tracker blocking.
- `--disable-resources` — speed option; can break pages.
- `--session` / `--user-data-dir <dir>` — use `StealthySession`; `--user-data-dir` persists browser state and implies session mode.
- `--warmup-url <url>` — fetch setup pages first in the same `StealthySession`; repeat for multiple warmups.
- `--real-chrome`, `--locale`, `--timezone-id`, `--no-browser-flags`, `--no-google-search` — useful when session consistency matters more than sandbox defaults.

Notes:

- `webfetch get` disables curl_cffi impersonation by default (`impersonate=None`).
- Keep `--main-content-only` on unless raw page fidelity matters.
- If browser commands fail with `ERR_CONNECTION_CLOSED`, confirm full network access and rerun setup.
- If `webfetch` is missing, run `scripts/setup.sh` or `./scripts/webfetch` from a checkout.
