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
  uvx --from "scrapling[fetchers]>=0.4.9,<0.5" scrapling install
```

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

Fast HTTP request through Scrapling's `Fetcher.get`. Uses `$HTTPS_PROXY` by
default when present. Browser impersonation is disabled by default
(`impersonate=None`) because some agent sandboxes have TLS/proxy stacks that are
incompatible with curl_cffi browser profiles. Set `SCRAPLING_IMPERSONATE=firefox`
or another curl_cffi profile only when you explicitly want impersonation.

```bash
webfetch get https://example.com --extraction-type markdown
```

### `fetch`

Dynamic Chromium fetch for JavaScript-rendered pages. Browser egress defaults to
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

Stealth Chromium fetch for bot protection / Cloudflare-style sites. Alias:
`stealthy_fetch`.

```bash
webfetch stealthy-fetch https://hard.example.com \
  --solve-cloudflare \
  --extraction-type text
```

## Options

| Option | Default | Notes |
|---|---:|---|
| `--extraction-type markdown|html|text` | `markdown` | Mirrors Scrapling MCP; Markdown uses `markdownify` |
| `--css-selector SELECTOR` | none | One output item per matching element |
| `--main-content-only / --no-main-content-only` | true | Body-scopes and sanitizes content before selector/extraction |
| `--wait-selector SELECTOR` | none | Browser commands only |
| `--network-idle` | false | Browser commands only |
| `--wait MS` | `0` | Browser commands only |
| `--disable-resources` | false | Browser commands only |
| `--block-ads / --no-block-ads` | true | Browser commands only; uses Scrapling's built-in ad/tracker domain blocking |
| `--proxy URL` | none for browsers | `get` uses `$HTTPS_PROXY` unless `--no-proxy` |

If a browser command returns only a cookie/consent shell, spinner, or empty page
frame, retry with hydration waits before changing backends:

```bash
webfetch fetch "https://www.coolblue.nl/zoeken?query=rtx%205060%20ti%2016gb" \
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

`--main-content-only` is enabled by default to match Scrapling MCP's
prompt-injection-protection ergonomics. Before applying `--css-selector` and
converting output, `webfetch` narrows to `<body>` and removes:

- `script`, `style`, `noscript`, `svg`, and `template` nodes
- `aria-hidden="true"` nodes
- common CSS-hidden nodes: `display:none`, `visibility:hidden`, `opacity:0`, and
  zero-size font/height/width nodes
- HTML comments
- zero-width Unicode characters

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
