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
ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\ufeff]")
HIDDEN_STYLE_PATTERNS = (
    re.compile(r"(?:^|;)\s*display\s*:\s*none\s*(?:;|$)", re.I),
    re.compile(r"(?:^|;)\s*visibility\s*:\s*hidden\s*(?:;|$)", re.I),
    re.compile(r"(?:^|;)\s*opacity\s*:\s*0\s*(?:;|$)", re.I),
    re.compile(r"(?:^|;)\s*font-size\s*:\s*0(?:px|em|rem|%)?\s*(?:;|$)", re.I),
    re.compile(r"(?:^|;)\s*height\s*:\s*0(?:px|em|rem|%)?\s*(?:;|$)", re.I),
    re.compile(r"(?:^|;)\s*width\s*:\s*0(?:px|em|rem|%)?\s*(?:;|$)", re.I),
)


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


def fetch_get(args: argparse.Namespace):
    from scrapling.fetchers import Fetcher

    kwargs: dict[str, Any] = {
        "follow_redirects": True,
        "stealthy_headers": True,
        "impersonate": impersonate_setting(),
        "timeout": args.timeout,
    }
    proxy = explicit_proxy(args)
    if proxy:
        kwargs["proxy"] = proxy
    return Fetcher.get(args.url, **kwargs)


def browser_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "headless": True,
        "timeout": args.timeout,
        "extra_flags": browser_flags(has_proxy=bool(args.proxy)),
    }
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
    return kwargs


def fetch_dynamic(args: argparse.Namespace):
    from scrapling.fetchers import DynamicFetcher

    kwargs = browser_kwargs(args)
    kwargs["additional_args"] = {"ignore_https_errors": True}
    return DynamicFetcher.fetch(args.url, **kwargs)


def fetch_stealthy(args: argparse.Namespace):
    from scrapling.fetchers import StealthyFetcher

    kwargs = browser_kwargs(args)
    kwargs["additional_args"] = {"ignore_https_errors": True}
    if args.solve_cloudflare:
        kwargs["solve_cloudflare"] = True
    return StealthyFetcher.fetch(args.url, **kwargs)


def html_of(target: Any) -> str:
    return getattr(target, "html_content", None) or getattr(target, "body", None) or str(target)


def remove_element(element: Any) -> None:
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def hidden_style(style: str) -> bool:
    return any(pattern.search(style or "") for pattern in HIDDEN_STYLE_PATTERNS)


def main_content_html(html: str) -> str:
    from lxml import html as lxml_html

    parser = lxml_html.HTMLParser(remove_comments=True)
    root = lxml_html.fromstring(html, parser=parser)
    bodies = root.xpath("//body")
    scope = bodies[0] if bodies else root

    xpath = (
        ".//script|.//style|.//noscript|.//svg|.//template|"
        ".//*[translate(@aria-hidden, 'TRUE', 'true')='true']"
    )
    for element in list(scope.xpath(xpath)):
        remove_element(element)
    for element in list(scope.xpath(".//*[@style]")):
        if hidden_style(element.get("style", "")):
            remove_element(element)

    return ZERO_WIDTH.sub("", lxml_html.tostring(scope, encoding="unicode", method="html"))


def text_from_html(html: str) -> str:
    from scrapling.parser import Adaptor

    text = Adaptor(html, url="").get_all_text(
        strip=True,
        ignore_tags=("script", "style", "noscript", "svg", "iframe"),
    )
    text = ZERO_WIDTH.sub("", str(text))
    return re.sub(r"[\n\r\t ]+", " ", text).strip()


def markdown_from_html(html: str) -> str:
    from markdownify import markdownify

    return markdownify(html).strip()


def content_of(target: Any, extraction_type: str) -> str:
    html = html_of(target)
    if extraction_type == "html":
        return html.strip()
    if extraction_type == "markdown":
        return markdown_from_html(html)
    if hasattr(target, "get_all_text"):
        text = target.get_all_text(
            strip=True,
            ignore_tags=("script", "style", "noscript", "svg", "iframe"),
        )
        return re.sub(r"[\n\r\t ]+", " ", ZERO_WIDTH.sub("", str(text))).strip()
    return text_from_html(html)


def extract_content(page: Any, args: argparse.Namespace) -> list[str]:
    from scrapling.parser import Adaptor

    html = html_of(page)
    if args.main_content_only:
        html = main_content_html(html)
    page = Adaptor(html, url=response_url(page, args.url))
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
        json.dump(
            {
                "status": response_status(page),
                "url": response_url(page, args.url),
                "content": extract_content(page, args),
            },
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


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("url")
    parser.add_argument("--extraction-type", choices=EXTRACTION_TYPES, default="markdown")
    parser.add_argument("--css-selector")
    parser.add_argument("--main-content-only", dest="main_content_only", action="store_true", default=True)
    parser.add_argument("--no-main-content-only", dest="main_content_only", action="store_false")
    parser.add_argument("--timeout", type=int, default=None)


def add_browser(parser: argparse.ArgumentParser) -> None:
    add_common(parser)
    parser.set_defaults(timeout=30000)
    parser.add_argument("--wait", type=int, default=0)
    parser.add_argument("--wait-selector")
    parser.add_argument("--network-idle", action="store_true")
    parser.add_argument("--disable-resources", action="store_true")
    parser.add_argument("--block-ads", dest="block_ads", action="store_true", default=True)
    parser.add_argument("--no-block-ads", dest="block_ads", action="store_false")
    parser.add_argument("--proxy", help="explicit browser proxy; unset by default")


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="webfetch")
    parser.add_argument("--version", action="store_true")
    subparsers = parser.add_subparsers(dest="command", parser_class=JsonArgumentParser)

    get_parser = subparsers.add_parser("get")
    add_common(get_parser)
    get_parser.set_defaults(fetcher=fetch_get, timeout=30)
    get_parser.add_argument("--proxy")
    get_parser.add_argument("--no-proxy", action="store_true")

    fetch_parser = subparsers.add_parser("fetch")
    add_browser(fetch_parser)
    fetch_parser.set_defaults(fetcher=fetch_dynamic)

    for name in ("stealthy-fetch", "stealthy_fetch"):
        stealth_parser = subparsers.add_parser(name)
        add_browser(stealth_parser)
        stealth_parser.add_argument("--solve-cloudflare", action="store_true")
        stealth_parser.set_defaults(fetcher=fetch_stealthy)

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_browser_path()
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
