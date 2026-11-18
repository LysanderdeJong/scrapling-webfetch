"""Offline checks. Run: python tests/test_cli.py"""
from types import SimpleNamespace

import re

from scrapling_webfetch.cli import build_parser, extract_content, parse_actions, search_snapshot, split_pairs

HTML = """<html><head><title>t</title></head><body>
<main><h1>Visible</h1><p class="item">one</p><p class="item">two​</p></main>
<div style="display:none !important">INJECT1</div>
<div style="max-height:0">INJECT2</div>
<div aria-hidden="true">INJECT3</div>
<slot hidden>INJECT4</slot>
<template>INJECT5</template>
<script>INJECT6</script>
<div style="opacity:0.95">kept</div>
</body></html>"""


def args(**kw):
    defaults = dict(url="https://x.test/", main_content_only=True, css_selector=None, extraction_type="text")
    return SimpleNamespace(**{**defaults, **kw})


def test_sanitizer_strips_hidden_content():
    text = extract_content(SimpleNamespace(html_content=HTML), args())[0]
    assert "Visible" in text and "kept" in text, text
    assert "INJECT" not in text, text
    assert "​" not in text


def test_selector_returns_one_item_per_match():
    out = extract_content(SimpleNamespace(html_content=HTML), args(css_selector=".item"))
    assert out == ["one", "two"], out


def test_raw_mode_keeps_hidden_content():
    text = extract_content(SimpleNamespace(html_content=HTML), args(main_content_only=False, extraction_type="html"))[0]
    assert "INJECT1" in text


def test_parser_aliases_and_new_flags():
    for cmd in ("fetch", "stealthy-fetch", "stealthy_fetch"):
        a = build_parser().parse_args([cmd, "https://x.test", "--solve-cloudflare", "--record-requests", "--pierce-shadow"])
        assert a.solve_cloudflare and a.pierce_shadow and a.record_requests == ""
    a = build_parser().parse_args(["fetch", "https://x.test", "--record-requests", "/api/", "--cdp-url", "http://h:9222"])
    assert a.record_requests == "/api/" and a.cdp_url == "http://h:9222" and not a.reuse_context


def test_parse_actions_validates_and_flattens():
    actions = parse_actions(['{"type":"click","target":"#a"}', '[{"type":"press_key","key":"Enter"},{"type":"click","x":1,"y":2}]'])
    assert [a["type"] for a in actions] == ["click", "press_key", "click"]
    for bad, message in (
        ('{"type":"tap"}', "unknown type"),
        ('{"type":"textbox","target":"#a"}', "needs value"),
        ('{"type":"click"}', "'target' or both"),
        ('{"type":"click","target":"#a","x":1,"y":2}', "'target' or both"),
    ):
        try:
            parse_actions([bad])
        except ValueError as exc:
            assert message in str(exc), exc
        else:
            raise AssertionError(f"accepted {bad}")


def test_search_snapshot_keeps_ancestors():
    snapshot = '- main:\n  - list:\n    - link "Home"\n    - link "Next"\n  - paragraph: hi'
    assert search_snapshot(snapshot, re.compile("Next")) == '- main:\n  - list:\n    - link "Next"'


def test_split_pairs():
    assert split_pairs(["X-A: 1:2", "Y: z"], ":", "--header") == {"X-A": "1:2", "Y": "z"}
    try:
        split_pairs(["novalue"], "=", "--cookie")
    except ValueError as exc:
        assert "--cookie" in str(exc)
    else:
        raise AssertionError("accepted malformed pair")


def test_get_parser_methods_and_snapshot_choice():
    a = build_parser().parse_args(["request", "https://x.test", "--method", "post", "--json", "{}", "--param", "q=1"])
    assert a.method == "POST" and a.param == ["q=1"]
    a = build_parser().parse_args(["fetch", "https://x.test", "--extraction-type", "snapshot", "--search", "Next"])
    assert a.extraction_type == "snapshot"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
