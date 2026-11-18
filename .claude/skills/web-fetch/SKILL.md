---
name: web-fetch
description: >-
  Fetch and operate web pages with the local webfetch CLI. Use when built-in
  fetch output is empty, blocked, or placeholder-only; when a page needs
  JavaScript rendering, Cloudflare/bot handling, or CSS-selector extraction;
  when the task needs clicking, form filling, or logging in; when you need the
  JSON API behind a page; or when you need a screenshot of a page.
---

# web-fetch

`webfetch` is a Scrapling-based CLI. Every call is one fresh browser (or HTTP
request) and prints one JSON object:

```json
{"status": 200, "url": "https://example.com/", "content": ["..."]}
```

Optional output fields: `network` (`--record-requests`), `evaluate`
(`--evaluate`), `screenshot` (absolute path, `--screenshot`). Errors go to
stderr as `{"error": {"type": ..., "message": ...}}` with a non-zero exit.
Exact flags: `webfetch get -h`, `webfetch fetch -h`.

## Reading a page: the ladder

1. `webfetch get URL` — plain HTTP, fastest. TLS impersonation is off by default; if `get` is blocked, try `SCRAPLING_IMPERSONATE=chrome webfetch get URL` before climbing.
2. `webfetch fetch URL` — real browser for JavaScript-rendered pages.
3. `webfetch fetch URL --solve-cloudflare` — bot protection.

A step is done when `content` holds the data you came for. A spinner, a consent
shell, a "verify you are human" page, or an empty list means climb one step, or
apply one recovery option below. Escalate one step at a time and say which step
you are on. (`stealthy-fetch` is an alias of `fetch`.)

Recovery options for `fetch`:

- Content hydrates late: `--network-idle --wait 3000`, or `--wait-selector '#content'` when you know the element.
- Blocked one-shot, fine in a real session: `--warmup-url https://site.example/` (fetches the homepage first in the same browser), plus `--real-chrome --locale nl-NL --timezone-id Europe/Amsterdam` for a consistent profile.
- Consent or login needed once: run `--headful --wait 60000 --save-state state.json`, let the human click through, then reuse with `--load-state state.json`.

## Shrinking output

`--css-selector` returns one `content` item per match; start broad
(`'main, [role="main"], article'`) and narrow. If a selector returns `[]`,
retry once without it: rendering may have worked and the selector be wrong.
Prefer semantic selectors and `data-testid` over generated class names.
`--extraction-type text` is the most compact; `markdown` (default) keeps links
and structure.

## Operating a page: look, then act

Each call starts a fresh browser, so a multi-step task is one call carrying all
its actions, with a look before it.

1. **Look.** `webfetch fetch URL --extraction-type snapshot --search 'Search|Login|Next'`
   returns the accessibility tree with `[ref=eN]` refs; `--search` keeps matching
   lines and their ancestors. Use it to find controls; it is far cheaper than
   markdown for that. Done when you can name a target for every control you need.
2. **Act.** Pass the steps as `--action` JSON (an object or an array; repeatable).
   The `content` you get back reflects the page after the actions, so add
   `--css-selector`, `--extraction-type`, or another snapshot to read the result.

```bash
webfetch fetch https://quotes.toscrape.com/login --action '[
  {"type": "textbox", "target": "#username", "value": "user"},
  {"type": "textbox", "target": "#password", "value": "secret"},
  {"type": "click", "target": "input[type=submit]"},
  {"type": "wait_element", "target": "a[href=\"/logout\"]"}
]' --extraction-type text
```

Action types (same schema as the Scrapling MCP `browser_actions` tool):

- Mouse: `click` / `move` (`target`, or `x`+`y`), `mouse_down`, `mouse_up`, `wheel` (`delta_x`, `delta_y`). `click` takes `button`, `click_count`, `delay`.
- Fields (`target` required): `textbox` (`value`, `clear` default true), `checkbox` (`value` true/false), `radio`, `combobox` (`value` = option label or list).
- Keys and dialogs: `press_key` (`key`, e.g. `Enter`, `ControlOrMeta+A`), `dialog` (`accept`, optional `prompt_text`).
- Waits: `wait_time` (`milliseconds`), `wait_element` (`target`, `state` default visible), `wait_load` (`state`: load, domcontentloaded, networkidle).

Rules that decide whether actions work:

- `target` is a Playwright selector: CSS, `text=Next`, `role=button[name="Search"]`, or `aria-ref=eN` from a snapshot. Refs are positional, so they hold only while the page structure matches the snapshot; for pages that change between loads, use CSS or `role=` targets.
- Place a `dialog` action before the action that opens the dialog.
- After a click that navigates, add `wait_load` or `wait_element` so the next step sees the new page.
- Actions run after page load and before `--wait-selector` / `--wait`, so those flags wait for the result of your actions.
- The first failing action stops the call with an error naming it (`Action 3 (click) failed: ...`). Fix that step, then rerun the whole chain.
- `--slowly` adds human-like delays for sites that flag instant typing.

## Getting the data behind a page

1. Record: `webfetch fetch URL --network-idle --record-requests '/api/'`. The `network` array lists XHR/fetch responses (`url`, `status`, `method`, `body`). Done when you have found the request that carries the data.
2. Call it directly, without a browser:
   `webfetch request 'https://site.example/api/items' --method POST --json '{"page": 2}' --header 'Accept: application/json' --extraction-type text --no-main-content-only`
   (`--param NAME=VALUE`, `--data`, `--cookie NAME=VALUE` also exist; `--data`/`--json` need a non-GET `--method`.)

Data embedded in page variables: `--evaluate '() => window.__NEXT_DATA__'`
runs in the page's own JavaScript world and puts the JSON result in `evaluate`.

## Seeing a page

`--screenshot shot.png` (add `--full-page` for the whole scroll height) saves an
image and puts its absolute path in `screenshot`; read that file to inspect
layout, captchas, or why `content` came back empty.

## Gotchas

- `--main-content-only` (default on) strips hidden prompt-injection text; turn it off with `--no-main-content-only` only for raw fidelity, such as reading JSON API bodies.
- `get`/`request` rejects redirects to private or internal IPs.
- Session-only features (`--record-requests`, `--save-state`, `--load-state`, `--evaluate`, `--screenshot`, snapshots) switch to session mode automatically.
- `--cdp-url URL --reuse-context` attaches to a Chromium the human already runs and reuses its logins; each call still opens a new tab.
- `ERR_CONNECTION_CLOSED` from browser commands: confirm network access and rerun `scripts/setup.sh`.
- `webfetch` missing: run `scripts/setup.sh`, or `./scripts/webfetch` from a checkout.
