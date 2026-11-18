# scrapling-webfetch

Minimal Scrapling-based `webfetch` CLI for AI agents. It keeps the useful shape
of Scrapling MCP tools without running an MCP server:

```bash
webfetch get URL
webfetch fetch URL
webfetch stealthy-fetch URL
```

Output is JSON on stdout:

```json
{"status": 200, "url": "https://example.com/", "content": ["Example Domain..."]}
```

Some flags add optional fields to the output:

- `network`: with `--record-requests`, an array of recorded XHR/fetch responses,
  each with `url`, `status`, `method`, `resource_type`, `body`, and an optional
  `body_note`.
- `evaluate`: with `--evaluate`, the JSON result of the JavaScript expression.
- `screenshot`: with `--screenshot`, the absolute path of the saved image.

With `--extraction-type snapshot`, `content` holds accessibility snapshots instead
of page text: one item for the page, or one per matching element with
`--css-selector`.

## Why This Exists

Scrapling already has a full MCP server and a general-purpose CLI. This tool is a
thin one-shot wrapper for agent environments that want:

- MCP-shaped commands (`get`, `fetch`, `stealthy-fetch`) without MCP transport.
- JSON responses with `content: string[]`.
- CSS selector extraction before returning content to the agent.
- `markdown`, `html`, and `text` output types matching Scrapling MCP semantics.
- Prompt-injection-conscious `main_content_only` extraction by default.
- Agent-sandbox browser defaults: browser commands avoid proxy environment
  variables via `--no-proxy-server` and tolerate transparent-MITM certs with
  `ignore_https_errors=True`.

## Install

From a public GitHub repo:

```bash
uv tool install "git+https://github.com/LysanderdeJong/scrapling-webfetch.git@main"
```

If your setup environment blocks Git transport but allows ordinary HTTPS
downloads, use the tarball flow in [`scripts/setup.sh`](scripts/setup.sh). It
downloads from `codeload.github.com`, installs from the extracted local directory,
and avoids `git clone` entirely.

From a local checkout:

```bash
uv tool install --reinstall --force .
```

Install Scrapling browser binaries and system dependencies:

```bash
PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
  uvx --from "scrapling[fetchers]==0.5.1" scrapling install
```

Only Patchright's Chromium is needed for the browser commands now.

For sandbox setup automation, see [`scripts/setup.sh`](scripts/setup.sh).

### Optional Claude Code Skill Install

Install the bundled Claude Code skill non-interactively with the `skills` CLI:

```bash
npx -y skills add LysanderdeJong/scrapling-webfetch \
  --skill web-fetch \
  --agent claude-code \
  --global \
  --yes \
  --copy
```

In a Claude Code web setup script, enable this path with:

```bash
INSTALL_CLAUDE_SKILL=1
CLAUDE_SKILL_HOME=/home/user  # optional; setup auto-detects this when running as root
```

`scripts/setup.sh` attempts this `npx skills add` command non-interactively and
falls back to copying the bundled `SKILL.md` directly if setup-time GitHub access
blocks the skills CLI. In automated sandbox setup, the script defaults to direct
copy for reliability; set `INSTALL_CLAUDE_SKILL_WITH_NPX=1` to force the `npx`
installer.

## Commands

### `get`

Fast HTTP request through Scrapling's `Fetcher`. `request` is an alias, so
`webfetch request URL` works too. Uses `$HTTPS_PROXY` by
default when present. Browser impersonation is disabled by default
(`impersonate=None`) because some agent sandboxes have TLS/proxy stacks that are
incompatible with curl_cffi browser profiles. Set `SCRAPLING_IMPERSONATE=firefox`
or another curl_cffi profile only when you explicitly want impersonation.

```bash
webfetch get https://example.com --extraction-type markdown
```

Use `--method` for other HTTP methods: `GET` (default), `POST`, `PUT`, or
`DELETE`. The method is case-insensitive. Send a form body with `--data` or a
JSON body with `--json`; both need a non-GET method and fail with an error on
`GET`. `--param NAME=VALUE` adds query parameters.

```bash
webfetch get https://api.example.com/items \
  --method POST \
  --json '{"name": "gpu", "qty": 2}' \
  --header 'Authorization: Bearer TOKEN' \
  --extraction-type text
```

Redirects use Scrapling's "safe" mode: a redirect to a private or internal IP
address is rejected.

### `fetch`

Patchright Chromium fetch for JavaScript-rendered and bot-protected pages.
Scrapling 0.5 dropped the plain Playwright backend and merged its browser
fetchers into `StealthyFetcher`, so `fetch` takes every browser flag, including
`--solve-cloudflare`. Browser egress defaults to
`--no-proxy-server --disable-quic`, and the command passes
`ignore_https_errors=True` for transparent-MITM agent sandboxes.

```bash
webfetch fetch https://app.example.com \
  --wait-selector '#root .loaded' \
  --network-idle \
  --css-selector '.card' \
  --extraction-type markdown
```

### `stealthy-fetch`

Compatibility alias for `fetch` (also `stealthy_fetch`). Kept so existing
scripts keep working; it behaves exactly like `fetch`.

```bash
webfetch stealthy-fetch https://hard.example.com \
  --solve-cloudflare \
  --extraction-type text
```

Some sites block one-shot browser fetches but allow a consistent browser session.
Use `--session`, `--warmup-url`, or `--user-data-dir` for those cases.

For sites that need a same-origin warmup, fetch the homepage before the search
page in the same session:

```bash
webfetch stealthy-fetch "https://marketplace.example/search?q=gpu" \
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

For consent-gated sites, run once headfully with a persistent profile, make the
consent choice manually, then reuse the same profile headless:

```bash
webfetch stealthy-fetch "https://community.example/" \
  --user-data-dir .consented-profile \
  --headful \
  --real-chrome \
  --no-browser-flags \
  --locale nl-NL \
  --timezone-id Europe/Amsterdam \
  --network-idle \
  --wait 60000 \
  --extraction-type text
```

To find the JSON API behind a JavaScript page, record the XHR/fetch traffic and
read the `network` array in the output:

```bash
webfetch fetch "https://app.example.com/search?q=gpu" \
  --network-idle \
  --record-requests '/api/' \
  --extraction-type text
```

To log in once and reuse the session later, save the state from a headful run and
load it in a later headless run:

```bash
webfetch fetch "https://app.example.com/login" \
  --headful \
  --network-idle \
  --wait 60000 \
  --save-state state.json \
  --extraction-type text

webfetch fetch "https://app.example.com/dashboard" \
  --load-state state.json \
  --network-idle \
  --extraction-type text
```

To use a Chromium you already started with `--remote-debugging-port=9222`, connect
over CDP and reuse its default context and login state:

```bash
webfetch fetch "https://app.example.com/dashboard" \
  --cdp-url http://localhost:9222 \
  --reuse-context \
  --extraction-type text
```

## Interacting with Pages

Browser commands can act on the page before the content is extracted. Actions run
after the page loads and before `--wait-selector` and `--wait`, so the output
reflects the page after the actions. Each `--action` takes one action object or an
array of them, and the flag can repeat. `--slowly` adds random delays between
actions and keystrokes. The first action that fails aborts the command with an
error JSON whose message names the action, for example `Action 3 (click) failed`.

### Logging In

```bash
webfetch fetch "https://quotes.toscrape.com/login" \
  --action '[
    {"type": "textbox", "target": "#username", "value": "demo"},
    {"type": "textbox", "target": "#password", "value": "demo"},
    {"type": "click", "target": "input[type=submit]"},
    {"type": "wait_element", "target": "a[href=\"/logout\"]"}
  ]' \
  --extraction-type text
```

Replace the demo values with real credentials. The `wait_element` action waits
for the logout link, so the extracted text is taken after the login completes.

### Snapshot, Then Click by Ref

`--extraction-type snapshot` returns an accessibility (ARIA) snapshot of the page.
Elements in the snapshot carry `[ref=eN]` markers. A later call can target one of
those elements with `aria-ref=eN`.

```bash
webfetch fetch "https://quotes.toscrape.com/" \
  --extraction-type snapshot \
  --search 'Next'
```

`--search` keeps the matching lines plus their ancestor lines, so the `Next`
link keeps its place in the tree. Note its `[ref=eN]`, then click it in a second
call:

```bash
webfetch fetch "https://quotes.toscrape.com/" \
  --action '{"type": "click", "target": "aria-ref=e94"}' \
  --action '{"type": "wait_load", "state": "load"}' \
  --extraction-type text
```

Refs are specific to the page structure at the time of the snapshot. The CLI takes
a fresh snapshot before it runs ref-targeted actions, so `aria-ref` works only
while the page structure matches the earlier snapshot. If the page has changed,
take a new snapshot and use the refs from it. After a click that navigates, add a
`wait_load` or `wait_element` action so extraction sees the new page.

`--snapshot-depth N` limits the tree depth, `--boxes` adds viewport bounding
boxes, and `--css-selector` returns one snapshot per matching element.

### Action Types

Each action is a JSON object with a `type` and the fields listed below. A
`target` is a Playwright selector: CSS (`#username`), text (`text=Sign in`), role
(`role=button[name="Search"]`), or `aria-ref=eN` from a snapshot. Where an action
has a `timeout`, it is in milliseconds and defaults to 30000.

| Type | Required fields | Optional fields | Notes |
|---|---|---|---|
| `click` | `target`, or both `x` and `y` | `button` (`left`), `click_count` (`1`), `delay`, `timeout` | Clicks an element, or the viewport point `x`, `y` |
| `move` | `target`, or both `x` and `y` | `steps` (`1`), `timeout` | Hovers an element, or moves the mouse to `x`, `y` |
| `mouse_down` | none | `button` (`left`) | Presses a mouse button at the current position |
| `mouse_up` | none | `button` (`left`) | Releases a mouse button at the current position |
| `wheel` | none | `delta_x` (`0`), `delta_y` (`0`) | Scrolls with the mouse wheel |
| `textbox` | `target`, `value` | `clear` (`true`), `timeout` | Clears the field unless `clear` is false, then types `value` |
| `checkbox` | `target`, `value` | `timeout` | Sets the checkbox to `true` or `false` |
| `radio` | `target` | `value` (`true`), `timeout` | Sets the radio button's checked state |
| `combobox` | `target`, `value` | `timeout` | Selects the option whose label is `value` |
| `press_key` | `key` | none | Presses a keyboard key, such as `Enter` |
| `dialog` | `accept` | `prompt_text` | Handles the next dialog: accepts when `accept` is true, dismisses otherwise. Must come before the action that opens the dialog |
| `wait_time` | `milliseconds` | none | Waits for a fixed time |
| `wait_element` | `target` | `state` (`visible`), `timeout` | Waits for an element to reach a state, such as `attached`, `detached`, `visible`, or `hidden` |
| `wait_load` | `state` | `timeout` | Waits for a Playwright load state |

### Screenshots and JavaScript

`--screenshot PATH` saves a PNG or JPEG, chosen by the file extension (`.png` or
`.jpg`), at CSS-pixel scale. `--full-page` captures the whole scrollable page. The
output's `screenshot` field holds the absolute path.

```bash
webfetch fetch "https://quotes.toscrape.com/" \
  --screenshot quotes.png \
  --full-page \
  --extraction-type text
```

`--evaluate JS` runs JavaScript in the page's main world, so it can read page
globals such as `window.__NEXT_DATA__`. The JSON result goes in the output's
`evaluate` field.

```bash
webfetch fetch "https://app.example.com/" \
  --evaluate 'window.__NEXT_DATA__?.buildId' \
  --extraction-type text
```

`--evaluate`, `--screenshot`, and `--extraction-type snapshot` read the live page
after the actions and waits finish, and they switch the command to session mode.

## Options

| Option | Default | Notes |
|---|---:|---|
| `--extraction-type markdown|html|text|snapshot` | `markdown` | Mirrors Scrapling MCP; Markdown uses `markdownify`; `snapshot` is browser only |
| `--css-selector SELECTOR` | none | One output item per matching element |
| `--main-content-only / --no-main-content-only` | true | Body-scopes and sanitizes content before selector/extraction |
| `--wait-selector SELECTOR` | none | Browser commands only |
| `--network-idle` | false | Browser commands only |
| `--wait MS` | `0` | Browser commands only |
| `--disable-resources` | false | Browser commands only |
| `--headless / --headful` | headless | Browser commands only; use headful for manual consent/login setup |
| `--block-ads / --no-block-ads` | true | Browser commands only; uses Scrapling's built-in ad/tracker domain blocking |
| `--proxy URL` | none for browsers | `get` uses `$HTTPS_PROXY` unless `--no-proxy` |
| `--real-chrome` | false | Browser commands only; use installed Chrome instead of bundled Chromium |
| `--locale LOCALE` | none | Browser commands only; passes Scrapling locale |
| `--timezone-id ZONE` | none | Browser commands only; passes Scrapling timezone |
| `--google-search / --no-google-search` | Scrapling default | Browser commands only; controls Google referrer behavior |
| `--no-browser-flags` | false | Browser commands only; disables this CLI's default Chromium flags |
| `--session` | false | Browser commands only; use `StealthySession` instead of one-shot `StealthyFetcher` |
| `--user-data-dir DIR` | none | Browser commands only; persistent browser profile, implies `--session` |
| `--warmup-url URL` | none | Browser commands only; fetch URL before the target in the same session, repeatable |
| `--solve-cloudflare` | false | Browser commands only |
| `--block-webrtc` | false | Browser commands only |
| `--hide-canvas` | false | Browser commands only |
| `--allow-webgl / --no-allow-webgl` | Scrapling default | Browser commands only |
| `--pierce-shadow` | false | Browser commands only; include open Shadow DOM content in the captured HTML |
| `--executable-path PATH` | none | Browser commands only; custom Chromium-compatible browser; falls back to `SCRAPLING_EXECUTABLE_PATH` |
| `--cdp-url URL` | none | Browser commands only; connect to an existing Chromium over an HTTP or WebSocket CDP endpoint (Scrapling `RemoteSession`); `--real-chrome` is ignored with it |
| `--reuse-context` | false | Browser commands only; with `--cdp-url`, reuse the browser's default context and login state; otherwise a separate context is created and closed afterwards |
| `--load-state PATH` | none | Browser commands only; restore cookies, localStorage, and IndexedDB from Playwright storage-state JSON (not sessionStorage); implies session mode |
| `--save-state PATH` | none | Browser commands only; save cookies, localStorage, and IndexedDB to Playwright storage-state JSON (not sessionStorage); implies session mode |
| `--record-requests [URL_REGEX]` | false | Browser commands only; record XHR/fetch traffic and HTTP errors during the session; matches (optionally regex-filtered, max 100) go in the output `network` array; implies session mode |
| `--header 'NAME: VALUE'` | none | All commands; extra request header, repeatable |
| `--cookie NAME=VALUE` | none | All commands; request cookie, repeatable; browser commands set it for the target URL |
| `--method METHOD` | `GET` | `get` only; `GET`, `POST`, `PUT`, or `DELETE`, case-insensitive |
| `--param NAME=VALUE` | none | `get` only; query parameter, repeatable |
| `--data STR` | none | `get` only; form or raw request body; needs a non-GET `--method` |
| `--json JSON` | none | `get` only; JSON request body; needs a non-GET `--method` |
| `--useragent UA` | none | Browser commands only |
| `--wait-selector-state STATE` | Scrapling default | Browser commands only; `attached`, `detached`, `visible`, or `hidden`; used with `--wait-selector` |
| `--action JSON` | none | Browser commands only; one action object or an array, repeatable; see [Interacting with Pages](#interacting-with-pages) |
| `--slowly` | false | Browser commands only; random delays between actions and keystrokes |
| `--evaluate JS` | none | Browser commands only; runs in the page's main world; result goes in the output `evaluate` field; implies session mode |
| `--screenshot PATH` | none | Browser commands only; `.png` or `.jpg` by extension; absolute path goes in the output `screenshot` field; implies session mode |
| `--full-page` | false | Browser commands only; with `--screenshot`, captures the whole scrollable page |
| `--snapshot-depth N` | none | Browser commands only; with `--extraction-type snapshot`, limits tree depth |
| `--boxes` | false | Browser commands only; with `--extraction-type snapshot`, adds viewport bounding boxes |
| `--search REGEX` | none | Browser commands only; with `--extraction-type snapshot`, keeps matching lines and their ancestors |

If a browser command returns only a cookie/consent shell, spinner, or empty page
frame, retry with hydration waits before changing backends:

```bash
webfetch fetch "https://shop.example/search?query=gpu" \
  --network-idle \
  --wait 3000 \
  --extraction-type markdown
```

### Selector Guidance

Use `--css-selector` to shrink output before handing it to an agent. Start broad,
then narrow:

```bash
webfetch fetch "https://shop.example.com/search?q=gpu" \
  --css-selector 'main, [role="main"], article' \
  --extraction-type markdown

webfetch fetch "https://shop.example.com/search?q=gpu" \
  --css-selector '.product, .product-card, [data-testid*="product"], [class*="product"]' \
  --extraction-type text
```

If a selector returns an empty `content` array, retry once without the selector to
check whether the selector is wrong or the page failed to render. Prefer stable
semantic selectors (`main`, `article`, `[role="main"]`, `data-testid`) over brittle
generated class names.

Errors are JSON on stderr with a non-zero exit:

```json
{"error": {"type": "Error", "message": "..."}}
```

## Prompt-Injection Protection

`--main-content-only` is enabled by default and uses Scrapling MCP's own
prompt-injection cleaning. Before applying `--css-selector` and converting
output, `webfetch` narrows to `<body>` and removes:

- `script`, `style`, `noscript`, `svg`, and `template` nodes
- `aria-hidden="true"` nodes and `<slot hidden>`
- inline-CSS-hidden nodes: `display:none`, `visibility:hidden`, and zero
  `opacity`/`font-size`/`height`/`width`/`max-height`/`max-width`, including
  `!important` and comment-obfuscated declarations
- HTML comments
- zero-width Unicode and control characters

Use `--no-main-content-only` when raw page fidelity matters more than safety.

## Agent Sandbox Notes

Browser commands intentionally bypass proxy environment variables by default:

```text
--no-proxy-server --disable-quic
```

Override with `SCRAPLING_CHROME_FLAGS` if your environment needs different
Chromium flags.

If `PLAYWRIGHT_BROWSERS_PATH` points at a missing directory but `/opt/pw-browsers`
exists, `webfetch` automatically uses `/opt/pw-browsers`. This matches hosted
agent images that preinstall Playwright browser revisions there.

The browser commands also pass `ignore_https_errors=True` because many hosted
agent sandboxes use transparent TLS inspection. This is a trust downgrade; run
web scraping in an isolated environment when possible.

## Optional Claude Skill

This repository includes `.claude/skills/web-fetch/SKILL.md` for Claude Code
users. The tool itself is not Claude-specific.

## Layout

```text
pyproject.toml                         # uv-tool package metadata
src/scrapling_webfetch/cli.py          # the CLI
scripts/setup.sh                       # sandbox setup helper
scripts/webfetch                       # checkout compatibility wrapper
.claude/skills/web-fetch/SKILL.md      # optional Claude skill
```

## Validate

```bash
webfetch --version
webfetch get https://example.com --extraction-type markdown
webfetch get https://example.com --css-selector h1 --extraction-type html
webfetch fetch https://example.com --extraction-type text
webfetch stealthy-fetch https://news.ycombinator.com --extraction-type text
```
