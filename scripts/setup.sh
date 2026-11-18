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

PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
WEBFETCH_REF="${WEBFETCH_REF:-main}"
INSTALL_CLAUDE_SKILL="${INSTALL_CLAUDE_SKILL:-1}"
INSTALL_CLAUDE_SKILL_WITH_NPX="${INSTALL_CLAUDE_SKILL_WITH_NPX:-0}"
WORKDIR=""

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

patchright_chrome_path() {
  "$TOOL_ENV/bin/python" - <<'PY'
from patchright.sync_api import sync_playwright
with sync_playwright() as p:
    print(p.chromium.executable_path)
PY
}

resolve_chrome_paths() {
  # Scrapling 0.5 drives Chromium only through Patchright. The only check that
  # matters: where does Patchright resolve chromium to, and is it executable.
  PATCHRIGHT_CHROME="$(patchright_chrome_path 2>/dev/null || true)"
}

verify_browser_binaries() {
  resolve_chrome_paths
  echo "[setup] Patchright expects: ${PATCHRIGHT_CHROME:-<unresolved>}"
  [ -n "$PATCHRIGHT_CHROME" ] && [ -x "$PATCHRIGHT_CHROME" ]
}

registry_is_valid() {
  # Quiet variant of verify_browser_binaries for candidate probing.
  resolve_chrome_paths
  [ -n "$PATCHRIGHT_CHROME" ] && [ -x "$PATCHRIGHT_CHROME" ]
}

choose_browser_registry() {
  local candidate
  for candidate in \
    "${PLAYWRIGHT_BROWSERS_PATH:-}" \
    "${PATCHRIGHT_BROWSERS_PATH:-}" \
    /opt/pw-browsers \
    /opt/ms-playwright \
    "$HOME/.cache/ms-playwright"; do
    [ -n "$candidate" ] || continue
    [ -d "$candidate" ] || continue
    export PLAYWRIGHT_BROWSERS_PATH="$candidate"
    export PATCHRIGHT_BROWSERS_PATH="$candidate"
    if registry_is_valid; then
      echo "[setup] using existing browser registry: $candidate"
      return 0
    fi
  done
  return 1
}

dump_browser_debug() {
  echo "[setup] browser dir: $PLAYWRIGHT_BROWSERS_PATH"
  ls -la "$PLAYWRIGHT_BROWSERS_PATH" 2>/dev/null || true
  find "$PLAYWRIGHT_BROWSERS_PATH" -maxdepth 4 -type f \( -name chrome -o -name chrome-headless-shell \) -print 2>/dev/null || true
}

install_browsers_only() {
  # Browser binaries only. Never `scrapling install` / `playwright install-deps`:
  # those run apt, which is broken on hosted images (ondrej/php PPA metadata).
  # OS-level deps are already present on these images, so we only fetch browsers.
  local target="${PLAYWRIGHT_BROWSERS_PATH:-/opt/pw-browsers}"
  if ! mkdir -p "$target" 2>/dev/null; then
    target="$HOME/.cache/ms-playwright"
    mkdir -p "$target"
  fi
  export PLAYWRIGHT_BROWSERS_PATH="$target"
  export PATCHRIGHT_BROWSERS_PATH="$target"
  echo "[setup] installing chromium (browser only, no OS deps) into: $target"
  NO_PROXY="localhost,127.0.0.1" no_proxy="localhost,127.0.0.1" \
    "$TOOL_ENV/bin/python" -m patchright install chromium
}

if choose_browser_registry; then
  echo "[setup] browser binaries verified"
else
  echo "[setup] no usable preinstalled browser registry found"
  install_browsers_only
  echo "[setup] verifying browser binaries after install"
  if ! verify_browser_binaries; then
    echo "[setup] ERROR: browser binaries still missing after install" >&2
    dump_browser_debug
    exit 1
  fi
  echo "[setup] browser binaries verified"
fi

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
