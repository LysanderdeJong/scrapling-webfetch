from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shlex
import sys
from typing import Any, Callable


DEFAULT_BROWSER_FLAGS = ["--no-proxy-server", "--disable-quic"]
EXTRACTION_TYPES = ("markdown", "html", "text")
AGENT_BROWSER_PATH = "/opt/pw-browsers"
DEFAULT_BROWSER_PATH = "/opt/ms-playwright"
ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\ufeff\u2060\u180e]")


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        json.dump({"error": {"type": "UsageError", "message": message}}, sys.stderr)
        sys.stderr.write("\n")
        raise SystemExit(2)


def configure_browser_path() -> None:
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if configured and os.path.exists(configured):
        return
    if os.path.exists(AGENT_BROWSER_PATH):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = AGENT_BROWSER_PATH
        os.environ.setdefault("PATCHRIGHT_BROWSERS_PATH", AGENT_BROWSER_PATH)
        return
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", DEFAULT_BROWSER_PATH)


def browser_flags(has_proxy: bool = False) -> list[str]:
    override = os.environ.get("SCRAPLING_CHROME_FLAGS")
    if override is not None:
        return shlex.split(override)
    if has_proxy:
        return [flag for flag in DEFAULT_BROWSER_FLAGS if flag != "--no-proxy-server"]
    return list(DEFAULT_BROWSER_FLAGS)


def explicit_proxy(args: argparse.Namespace) -> str | None:
    if getattr(args, "no_proxy", False):
        return None
    return getattr(args, "proxy", None) or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")


def impersonate_setting() -> str | None:
    value = os.environ.get("SCRAPLING_IMPERSONATE")
    if value is None or value.strip().lower() in {"", "none", "null", "false", "off"}:
        return None
    return value


def split_pairs(values: list[str], sep: str, flag: str) -> dict[str, str]:
    pairs = {}
    for value in values:
        key, found, rest = value.partition(sep)
        if not found or not key.strip():
            raise ValueError(f"{flag} expects NAME{sep}VALUE, got {value!r}")
        pairs[key.strip()] = rest.strip()
    return pairs


def fetch_get(args: argparse.Namespace):
    from scrapling.fetchers import Fetcher

    # follow_redirects keeps Scrapling's "safe" default: redirects to private/internal IPs are rejected.
    kwargs: dict[str, Any] = {
        "stealthy_headers": True,
        "impersonate": impersonate_setting(),
        "timeout": args.timeout,
    }
    proxy = explicit_proxy(args)
    if proxy:
        kwargs["proxy"] = proxy
    if args.header:
        kwargs["headers"] = split_pairs(args.header, ":", "--header")
    if args.cookie:
        kwargs["cookies"] = split_pairs(args.cookie, "=", "--cookie")
    if args.param:
        kwargs["params"] = split_pairs(args.param, "=", "--param")
    if args.data is not None or args.json is not None:
        if args.method == "GET":
            raise ValueError("--data/--json need --method POST, PUT or DELETE")
        if args.data is not None:
            kwargs["data"] = args.data
        if args.json is not None:
            kwargs["json"] = json.loads(args.json)
    return getattr(Fetcher, args.method.lower())(args.url, **kwargs)


def browser_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "headless": args.headless,
        "timeout": args.timeout,
    }
    if not args.no_browser_flags:
        kwargs["extra_flags"] = browser_flags(has_proxy=bool(args.proxy))
    if args.wait:
        kwargs["wait"] = args.wait
    if args.wait_selector:
        kwargs["wait_selector"] = args.wait_selector
    if args.network_idle:
        kwargs["network_idle"] = True
    if args.disable_resources:
        kwargs["disable_resources"] = True
    if args.block_ads:
        kwargs["block_ads"] = True
    if args.proxy:
        kwargs["proxy"] = args.proxy
    if getattr(args, "real_chrome", False):
        kwargs["real_chrome"] = True
    if getattr(args, "locale", None):
        kwargs["locale"] = args.locale
    if getattr(args, "timezone_id", None):
        kwargs["timezone_id"] = args.timezone_id
    if getattr(args, "google_search", None) is not None:
        kwargs["google_search"] = args.google_search
    if args.pierce_shadow:
        kwargs["pierce_shadow"] = True
    executable_path = args.executable_path or os.environ.get("SCRAPLING_EXECUTABLE_PATH")
    if executable_path:
        kwargs["executable_path"] = executable_path
    if args.user_data_dir:
        kwargs["user_data_dir"] = args.user_data_dir
    if args.record_requests is not None:
        kwargs["record_requests"] = True
    if args.solve_cloudflare:
        kwargs["solve_cloudflare"] = True
    if args.block_webrtc:
        kwargs["block_webrtc"] = True
    if args.hide_canvas:
        kwargs["hide_canvas"] = True
    if args.allow_webgl is not None:
        kwargs["allow_webgl"] = args.allow_webgl
    if args.header:
        kwargs["extra_headers"] = split_pairs(args.header, ":", "--header")
    if args.cookie:
        cookies = split_pairs(args.cookie, "=", "--cookie")
        kwargs["cookies"] = [{"name": name, "value": value, "url": args.url} for name, value in cookies.items()]
    if args.useragent:
        kwargs["useragent"] = args.useragent
    if args.wait_selector_state:
        kwargs["wait_selector_state"] = args.wait_selector_state
    return kwargs


# Same action JSON as the Scrapling MCP `browser_actions` tool, so agents can reuse what they know.
# ponytail: sync subset of scrapling.core.ai._browser_actions (importing that pulls in the whole MCP server).
ACTION_FIELDS: dict[str, tuple[str, ...]] = {
    "click": (), "move": (), "mouse_down": (), "mouse_up": (), "wheel": (),
    "textbox": ("target", "value"), "checkbox": ("target", "value"), "radio": ("target",),
    "combobox": ("target", "value"), "press_key": ("key",), "dialog": ("accept",),
    "wait_time": ("milliseconds",), "wait_element": ("target",), "wait_load": ("state",),
}


def parse_actions(raw: list[str]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for value in raw:
        parsed = json.loads(value)
        actions.extend(parsed if isinstance(parsed, list) else [parsed])
    for index, action in enumerate(actions, 1):
        kind = action.get("type") if isinstance(action, dict) else None
        if kind not in ACTION_FIELDS:
            raise ValueError(f"Action {index}: unknown type {kind!r}; expected one of {', '.join(ACTION_FIELDS)}")
        missing = [field for field in ACTION_FIELDS[kind] if field not in action]
        if missing:
            raise ValueError(f"Action {index} ({kind}) needs {', '.join(missing)}")
        if kind in ("click", "move") and ("target" in action) == ("x" in action and "y" in action):
            raise ValueError(f"Action {index} ({kind}) needs 'target' or both 'x' and 'y', not both")
    return actions


def run_actions(page: Any, actions: list[dict[str, Any]], slowly: bool = False) -> None:
    import random

    if any(str(action.get("target", "")).startswith("aria-ref=") for action in actions):
        page.aria_snapshot(mode="ai")  # refs only resolve after a snapshot of the current page
    for index, action in enumerate(actions, 1):
        kind, target = action["type"], action.get("target")
        timeout = action.get("timeout", 30000)
        locator = page.locator(target) if target else None
        try:
            if slowly and index > 1:
                page.wait_for_timeout(random.uniform(100, 300))
            if kind == "click":
                options = {"button": action.get("button", "left"), "click_count": action.get("click_count", 1), "delay": action.get("delay", 0)}
                if locator:
                    locator.click(timeout=timeout, **options)
                else:
                    page.mouse.click(action["x"], action["y"], **options)
            elif kind == "move":
                if locator:
                    locator.hover(timeout=timeout)
                else:
                    page.mouse.move(action["x"], action["y"], steps=action.get("steps", 1))
            elif kind == "mouse_down":
                page.mouse.down(button=action.get("button", "left"))
            elif kind == "mouse_up":
                page.mouse.up(button=action.get("button", "left"))
            elif kind == "wheel":
                page.mouse.wheel(action.get("delta_x", 0), action.get("delta_y", 0))
            elif kind == "textbox":
                if action.get("clear", True):
                    locator.fill("", timeout=timeout)
                locator.press_sequentially(action["value"], delay=random.uniform(50, 150) if slowly else 0, timeout=timeout)
            elif kind in ("checkbox", "radio"):
                locator.set_checked(bool(action.get("value", True)), timeout=timeout)
            elif kind == "combobox":
                locator.select_option(label=action["value"], timeout=timeout)
            elif kind == "press_key":
                page.keyboard.press(action["key"])
            elif kind == "dialog":
                accept, text = action["accept"], action.get("prompt_text")
                page.once("dialog", lambda dialog: dialog.accept(prompt_text=text) if accept else dialog.dismiss())
            elif kind == "wait_time":
                page.wait_for_timeout(action["milliseconds"])
            elif kind == "wait_element":
                locator.wait_for(state=action.get("state", "visible"), timeout=timeout)
            elif kind == "wait_load":
                page.wait_for_load_state(action["state"], timeout=timeout)
        except Exception as exc:
            raise RuntimeError(f"Action {index} ({kind}) failed: {exc}") from exc


def search_snapshot(snapshot: str, pattern: re.Pattern[str]) -> str:
    """Keep matching lines plus their ancestor lines, so each match keeps its place in the tree."""
    lines = snapshot.splitlines()
    keep: set[int] = set()
    for index, line in enumerate(lines):
        if not pattern.search(line):
            continue
        keep.add(index)
        indent = len(line) - len(line.lstrip())
        for parent in range(index - 1, -1, -1):
            parent_indent = len(lines[parent]) - len(lines[parent].lstrip())
            if parent_indent < indent:
                keep.add(parent)
                indent = parent_indent
    return "\n".join(lines[index] for index in sorted(keep))


def snapshot_content(page: Any, args: argparse.Namespace) -> list[str]:
    if args.css_selector:
        locator = page.locator(args.css_selector)
        targets = [locator.nth(index) for index in range(locator.count())]
    else:
        targets = [page]
    snapshots = [target.aria_snapshot(mode="ai", depth=args.snapshot_depth, boxes=args.boxes) for target in targets]
    if args.search:
        pattern = re.compile(args.search)
        snapshots = [search_snapshot(snapshot, pattern) for snapshot in snapshots]
    return snapshots


def inspect_page(page: Any, args: argparse.Namespace) -> dict[str, Any]:
    """Read the live page after the fetch (and any actions, waits) finished."""
    extra: dict[str, Any] = {}
    if args.evaluate:
        extra["evaluate"] = page.evaluate(args.evaluate, isolated_context=False)
    if args.screenshot:
        page.screenshot(path=args.screenshot, full_page=args.full_page, scale="css")
        extra["screenshot"] = os.path.abspath(args.screenshot)
    if args.extraction_type == "snapshot":
        extra["content"] = snapshot_content(page, args)
    return extra


def network_entry(response: Any) -> dict[str, Any]:
    meta = getattr(response, "meta", None) or {}
    body = response.body
    entry = {
        "url": response.url,
        "status": response.status,
        "method": getattr(response, "method", None),
        "resource_type": meta.get("resource_type"),
        "body": body.decode("utf-8", "replace") if isinstance(body, bytes) else body,
    }
    if meta.get("body_note"):
        entry["body_note"] = meta["body_note"]
    return entry


def fetch_browser(args: argparse.Namespace):
    # Scrapling 0.5 removed the plain Playwright backend: `fetch` and `stealthy-fetch` both run Patchright.
    kwargs = browser_kwargs(args)
    kwargs["additional_args"] = {"ignore_https_errors": True}
    actions = parse_actions(args.action)
    inspect = bool(args.evaluate or args.screenshot or args.extraction_type == "snapshot")
    live: dict[str, Any] = {}

    def page_action(page: Any) -> None:
        # Scrapling only logs page_action errors, so keep the error and raise it after the fetch.
        live["page"] = page
        try:
            run_actions(page, actions, args.slowly)
        except Exception as exc:
            live["error"] = exc

    def target_fetch(fetch: Callable[..., Any]) -> Any:
        page = fetch(args.url, page_action=page_action) if actions or inspect else fetch(args.url)
        if "error" in live:
            raise live["error"]
        return page

    use_session = (
        args.session or args.user_data_dir or args.warmup_url or args.cdp_url or inspect
        or args.load_state or args.save_state or args.record_requests is not None
    )
    if not use_session:
        from scrapling.fetchers import StealthyFetcher

        return target_fetch(lambda url, **extra: StealthyFetcher.fetch(url, **kwargs, **extra))

    if args.cdp_url:
        from scrapling.fetchers import RemoteSession

        kwargs.pop("real_chrome", None)  # cdp_url selects the browser
        session_cm = RemoteSession(cdp_url=args.cdp_url, new_context=not args.reuse_context, **kwargs)
    else:
        from scrapling.fetchers import StealthySession

        session_cm = StealthySession(**kwargs)
    with session_cm as session:
        if args.load_state:
            session.load_state(args.load_state)
        for warmup_url in args.warmup_url:
            session.fetch(warmup_url)
        page = target_fetch(session.fetch)
        if inspect:
            page.webfetch_extra = inspect_page(live["page"], args)  # the session keeps the tab open
        if args.save_state:
            session.save_state(args.save_state)
        if args.record_requests is not None:
            matches = session.network.search(url_pattern=args.record_requests or None, include_static=False)
            page.webfetch_network = [network_entry(response) for response in matches]
        return page


def html_of(target: Any) -> str:
    return getattr(target, "html_content", None) or getattr(target, "body", None) or str(target)


def content_of(target: Any, extraction_type: str) -> str:
    html = html_of(target)
    if extraction_type == "html":
        return html.strip()
    if extraction_type == "markdown":
        from markdownify import markdownify

        return markdownify(html).strip()
    text = target.get_all_text(strip=True, ignore_tags=("script", "style", "noscript", "svg", "iframe"))
    return re.sub(r"[\n\r\t ]+", " ", ZERO_WIDTH.sub("", str(text))).strip()


def extract_content(page: Any, args: argparse.Namespace) -> list[str]:
    from scrapling.core.shell import Convertor
    from scrapling.parser import Selector

    page = Selector(html_of(page), url=response_url(page, args.url))
    if args.main_content_only:
        # ponytail: reuse Scrapling's MCP sanitizer (private API, safe while scrapling is pinned with ==).
        page = page.css("body").first or page
        page = Convertor._sanitize_for_ai(Convertor._strip_noise_tags(page))
    if args.css_selector:
        targets = list(page.css(args.css_selector))
    else:
        targets = [page]
    return [content_of(target, args.extraction_type) for target in targets]


def response_url(page: Any, fallback: str) -> str:
    return getattr(page, "url", None) or getattr(page, "final_url", None) or fallback


def response_status(page: Any) -> int | None:
    for name in ("status", "status_code"):
        value = getattr(page, name, None)
        if isinstance(value, int):
            return value
    return None


def run(args: argparse.Namespace, fetcher: Callable[[argparse.Namespace], Any]) -> int:
    logs = io.StringIO()
    try:
        with contextlib.redirect_stderr(logs):
            page = fetcher(args)
        extra = dict(getattr(page, "webfetch_extra", {}))
        result: dict[str, Any] = {
            "status": response_status(page),
            "url": response_url(page, args.url),
            "content": extra.pop("content") if "content" in extra else extract_content(page, args),
            **extra,
        }
        network = getattr(page, "webfetch_network", None)
        if network is not None:
            result["network"] = network
        json.dump(
            result,
            sys.stdout,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")
        return 0
    except Exception as exc:
        error: dict[str, Any] = {"type": type(exc).__name__, "message": str(exc)}
        if os.environ.get("WEBFETCH_DEBUG"):
            error["logs"] = logs.getvalue().splitlines()
        json.dump({"error": error}, sys.stderr)
        sys.stderr.write("\n")
        return 1


def add_common(parser: argparse.ArgumentParser, extraction_types: tuple[str, ...] = EXTRACTION_TYPES) -> None:
    parser.add_argument("url")
    parser.add_argument("--extraction-type", choices=extraction_types, default="markdown")
    parser.add_argument("--css-selector")
    parser.add_argument("--main-content-only", dest="main_content_only", action="store_true", default=True)
    parser.add_argument("--no-main-content-only", dest="main_content_only", action="store_false")
    parser.add_argument("--timeout", type=int, default=None)
    parser.add_argument("--header", action="append", default=[], metavar="'NAME: VALUE'", help="extra request header; repeatable")
    parser.add_argument("--cookie", action="append", default=[], metavar="NAME=VALUE", help="request cookie; repeatable")


def add_browser(parser: argparse.ArgumentParser) -> None:
    add_common(parser, EXTRACTION_TYPES + ("snapshot",))
    parser.set_defaults(timeout=30000)
    parser.add_argument("--wait", type=int, default=0)
    parser.add_argument("--wait-selector")
    parser.add_argument("--network-idle", action="store_true")
    parser.add_argument("--disable-resources", action="store_true")
    parser.add_argument("--headless", dest="headless", action="store_true", default=True)
    parser.add_argument("--headful", dest="headless", action="store_false")
    parser.add_argument("--block-ads", dest="block_ads", action="store_true", default=True)
    parser.add_argument("--no-block-ads", dest="block_ads", action="store_false")
    parser.add_argument("--proxy", help="explicit browser proxy; unset by default")
    parser.add_argument("--no-browser-flags", action="store_true", help="do not pass default Chromium flags")
    parser.add_argument("--real-chrome", action="store_true")
    parser.add_argument("--locale")
    parser.add_argument("--timezone-id")
    parser.add_argument("--google-search", dest="google_search", action="store_true", default=None)
    parser.add_argument("--no-google-search", dest="google_search", action="store_false")
    parser.add_argument("--pierce-shadow", action="store_true", help="include open Shadow DOM content in the captured HTML")
    parser.add_argument("--executable-path", help="custom Chromium-compatible browser; falls back to SCRAPLING_EXECUTABLE_PATH")
    parser.add_argument("--session", action="store_true", help="use a browser session instead of a one-shot fetch")
    parser.add_argument("--user-data-dir", help="persistent browser profile directory; implies --session")
    parser.add_argument("--warmup-url", action="append", default=[], help="fetch this URL first in the same session; repeatable")
    parser.add_argument("--cdp-url", help="connect to an existing Chromium over an HTTP/WebSocket CDP endpoint (RemoteSession)")
    parser.add_argument("--reuse-context", action="store_true", help="with --cdp-url: reuse the browser's default context and login state")
    parser.add_argument("--load-state", metavar="PATH", help="restore cookies/localStorage/IndexedDB from a Playwright storage-state JSON")
    parser.add_argument("--save-state", metavar="PATH", help="save cookies/localStorage/IndexedDB to a Playwright storage-state JSON")
    parser.add_argument(
        "--record-requests", nargs="?", const="", metavar="URL_REGEX",
        help="record XHR/fetch traffic and HTTP errors; matches (optionally regex-filtered) go in the output's network field",
    )
    parser.add_argument("--solve-cloudflare", action="store_true")
    parser.add_argument("--block-webrtc", action="store_true")
    parser.add_argument("--hide-canvas", action="store_true")
    parser.add_argument("--allow-webgl", dest="allow_webgl", action="store_true", default=None)
    parser.add_argument("--no-allow-webgl", dest="allow_webgl", action="store_false")
    parser.add_argument("--useragent")
    parser.add_argument("--wait-selector-state", choices=("attached", "detached", "visible", "hidden"))
    parser.add_argument(
        "--action", action="append", default=[], metavar="JSON",
        help="browser action object or array (Scrapling MCP browser_actions schema), run after load; repeatable",
    )
    parser.add_argument("--slowly", action="store_true", help="human-like random delays between actions and keystrokes")
    parser.add_argument("--evaluate", metavar="JS", help="run JavaScript in the page's main world; result goes in the output's evaluate field")
    parser.add_argument("--screenshot", metavar="PATH", help="save a PNG/JPEG screenshot; its absolute path goes in the output")
    parser.add_argument("--full-page", action="store_true", help="with --screenshot: capture the full scrollable page")
    parser.add_argument("--snapshot-depth", type=int, help="with --extraction-type snapshot: limit tree depth")
    parser.add_argument("--boxes", action="store_true", help="with --extraction-type snapshot: include viewport bounding boxes")
    parser.add_argument("--search", metavar="REGEX", help="with --extraction-type snapshot: keep matching lines and their ancestors")


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="webfetch")
    parser.add_argument("--version", action="store_true")
    subparsers = parser.add_subparsers(dest="command", parser_class=JsonArgumentParser)

    get_parser = subparsers.add_parser("get", aliases=["request"])
    add_common(get_parser)
    get_parser.set_defaults(fetcher=fetch_get, timeout=30)
    get_parser.add_argument("--method", choices=("GET", "POST", "PUT", "DELETE"), default="GET", type=str.upper)
    get_parser.add_argument("--param", action="append", default=[], metavar="NAME=VALUE", help="query parameter; repeatable")
    get_parser.add_argument("--data", help="form or raw request body (non-GET)")
    get_parser.add_argument("--json", help="JSON request body (non-GET)")
    get_parser.add_argument("--proxy")
    get_parser.add_argument("--no-proxy", action="store_true")

    # Scrapling 0.5 has a single (Patchright) browser backend; `stealthy-fetch` stays as a compatibility alias.
    fetch_parser = subparsers.add_parser("fetch", aliases=["stealthy-fetch", "stealthy_fetch"])
    add_browser(fetch_parser)
    fetch_parser.set_defaults(fetcher=fetch_browser)

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_browser_path()
    sys.stdout.reconfigure(encoding="utf-8")  # ensure_ascii=False output breaks on non-UTF-8 consoles (Windows)
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        from scrapling_webfetch import __version__

        print(__version__)
        return 0
    if not getattr(args, "command", None):
        json.dump({"error": {"type": "UsageError", "message": "command is required"}}, sys.stderr)
        sys.stderr.write("\n")
        return 2
    return run(args, args.fetcher)


if __name__ == "__main__":
    raise SystemExit(main())
