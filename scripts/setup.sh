#!/usr/bin/env bash
#
# Environment setup for scrapling-webfetch in an agent sandbox.
#
# Paste this file into the environment Setup script, or run it manually from the
# repo checkout. It installs the `webfetch` CLI as a uv tool and downloads the
# browser binaries/system dependencies Scrapling needs.
#
# Prerequisite: Network access must be set to Full.
set -euo pipefail

if [ -z "${PLAYWRIGHT_BROWSERS_PATH:-}" ] && [ -d /opt/pw-browsers ]; then
  export PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
else
  export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/opt/ms-playwright}"
fi
export PATCHRIGHT_BROWSERS_PATH="${PATCHRIGHT_BROWSERS_PATH:-$PLAYWRIGHT_BROWSERS_PATH}"
PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
WEBFETCH_REF="${WEBFETCH_REF:-main}"
INSTALL_CLAUDE_SKILL="${INSTALL_CLAUDE_SKILL:-1}"
INSTALL_CLAUDE_SKILL_WITH_NPX="${INSTALL_CLAUDE_SKILL_WITH_NPX:-0}"
WORKDIR=""

if [ "$PLAYWRIGHT_BROWSERS_PATH" = "/opt/ms-playwright" ] && [ -d /opt/pw-browsers ]; then
  # Hosted agent images may already contain the matching browser revisions in
  # /opt/pw-browsers while user env points Playwright at /opt/ms-playwright.
  # Bridge the two paths instead of re-downloading browsers.
  if [ ! -e /opt/ms-playwright ]; then
    ln -s /opt/pw-browsers /opt/ms-playwright
  elif [ -d /opt/ms-playwright ] && rmdir /opt/ms-playwright 2>/dev/null; then
    ln -s /opt/pw-browsers /opt/ms-playwright
  fi
fi

cleanup() {
  if [ -n "$WORKDIR" ]; then
    rm -rf "$WORKDIR"
  fi
}
trap cleanup EXIT

if ! command -v uv >/dev/null 2>&1; then
  echo "[setup] installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

export PATH="$(uv tool dir --bin):$HOME/.local/bin:$PATH"

if [ -n "${WEBFETCH_TOOL_SPEC:-}" ]; then
  TOOL_SPEC="$WEBFETCH_TOOL_SPEC"
elif [ -f "./pyproject.toml" ] && grep -q 'name = "scrapling-webfetch"' ./pyproject.toml; then
  TOOL_SPEC="$PWD"
else
  WORKDIR="$(mktemp -d)"
  echo "[setup] downloading scrapling-webfetch tarball ($WEBFETCH_REF)"
  curl -LsSf "https://codeload.github.com/LysanderdeJong/scrapling-webfetch/tar.gz/${WEBFETCH_REF}" \
    -o "$WORKDIR/scrapling-webfetch.tar.gz"
  tar -xzf "$WORKDIR/scrapling-webfetch.tar.gz" -C "$WORKDIR"
  TOOL_SPEC="$(find "$WORKDIR" -maxdepth 1 -type d -name 'scrapling-webfetch-*' | head -1)"
fi

echo "[setup] installing webfetch uv tool from: $TOOL_SPEC"
uv tool install --python "$PYTHON_VERSION" --reinstall --force "$TOOL_SPEC"

# Make the command available even if uv's tool bin dir is not on future PATHs.
TOOL_BIN="$(uv tool dir --bin)/webfetch"
if [ -x "$TOOL_BIN" ]; then
  ln -sf "$TOOL_BIN" /usr/local/bin/webfetch 2>/dev/null || true
fi

TOOL_ENV="$(uv tool dir)/scrapling-webfetch"
if [ ! -x "$TOOL_ENV/bin/python" ]; then
  echo "[setup] ERROR: uv tool environment not found at $TOOL_ENV" >&2
  exit 1
fi

install_claude_skill_for_home() {
  local target_home="$1"
  [ -d "$target_home" ] || return 0
  echo "[setup] installing Claude Code skill into $target_home/.claude/skills"
  if [ "$INSTALL_CLAUDE_SKILL_WITH_NPX" = "1" ] && command -v npx >/dev/null 2>&1 && HOME="$target_home" npx -y skills add LysanderdeJong/scrapling-webfetch \
    --skill web-fetch \
    --agent claude-code \
    --global \
    --yes \
    --copy; then
    return 0
  fi

  echo "[setup] npx skill install failed; copying bundled skill directly"
  mkdir -p "$target_home/.claude/skills/web-fetch"
  cp "$TOOL_SPEC/.claude/skills/web-fetch/SKILL.md" \
    "$target_home/.claude/skills/web-fetch/SKILL.md"
}

playwright_chrome_path() {
  "$TOOL_ENV/bin/python" - <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    print(p.chromium.executable_path)
PY
}

patchright_chrome_path() {
  "$TOOL_ENV/bin/python" - <<'PY'
from patchright.sync_api import sync_playwright
with sync_playwright() as p:
    print(p.chromium.executable_path)
PY
}

verify_browser_binaries() {
  PLAYWRIGHT_CHROME="$(playwright_chrome_path)"
  PATCHRIGHT_CHROME="$(patchright_chrome_path)"

  echo "[setup] Playwright expects: $PLAYWRIGHT_CHROME"
  echo "[setup] Patchright expects:  $PATCHRIGHT_CHROME"

  [ -x "$PLAYWRIGHT_CHROME" ] && [ -x "$PATCHRIGHT_CHROME" ]
}

dump_browser_debug() {
  echo "[setup] browser dir: $PLAYWRIGHT_BROWSERS_PATH"
  ls -la "$PLAYWRIGHT_BROWSERS_PATH" 2>/dev/null || true
  find "$PLAYWRIGHT_BROWSERS_PATH" -maxdepth 4 -type f \( -name chrome -o -name chrome-headless-shell \) -print 2>/dev/null || true
}

# `scrapling install` is the canonical browser/dependency install. Run it from
# the same uv tool environment that webfetch uses so Playwright/Patchright agree
# on the browser registry and revision.
echo "[setup] downloading Scrapling browser binaries + system deps"
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"
NO_PROXY="localhost,127.0.0.1" no_proxy="localhost,127.0.0.1" \
  "$TOOL_ENV/bin/scrapling" install

echo "[setup] verifying browser binaries after scrapling install"
if ! verify_browser_binaries; then
  echo "[setup] ERROR: scrapling install did not provide the browser binaries webfetch needs" >&2
  dump_browser_debug
  exit 1
fi

echo "[setup] browser binaries verified"

if [ "$INSTALL_CLAUDE_SKILL" = "1" ]; then
  install_claude_skill_for_home "${CLAUDE_SKILL_HOME:-$HOME}"
  if [ -d /home/user ] && [ "${CLAUDE_SKILL_HOME:-$HOME}" != "/home/user" ]; then
    install_claude_skill_for_home /home/user
  fi
fi

echo "[setup] done"
echo "[setup] browsers: $PLAYWRIGHT_BROWSERS_PATH"
echo "[setup] patchright browsers: $PATCHRIGHT_BROWSERS_PATH"
echo "[setup] tool:     $(command -v webfetch || true)"
echo "[setup] test:     webfetch fetch https://example.com --extraction-type text"
