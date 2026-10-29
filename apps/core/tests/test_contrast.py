"""WCAG AA contrast of the colour tokens in assets/css/input.css, in light and
dark mode: 4.5:1 for text, 3:1 for form-field borders and focus colours."""

import re
from pathlib import Path

import pytest

CSS = Path(__file__).resolve().parents[3] / "assets" / "css" / "input.css"

# (text or foreground, background) pairs that appear on our pages.
TEXT_PAIRS = [
    *[(fg, bg) for fg in ("ink", "ink-soft", "muted", "link") for bg in ("surface", "canvas")],
    *[(fg, "subtle") for fg in ("ink", "ink-soft", "muted", "link")],
    *[(fg, bg) for fg in ("danger", "success", "warning") for bg in ("surface", "canvas")],
    ("ink", "accent-soft"),
    ("link", "accent-soft"),
    ("muted", "accent-soft"),
    ("danger", "danger-soft"),
    ("success", "success-soft"),
    ("warning", "warning-soft"),
    ("ink", "warning-soft"),
    *[
        ("on-accent", bg)
        for bg in (
            "accent",
            "accent-strong",
            "danger-strong",
            "danger-stronger",
            "success-strong",
            "success-stronger",
        )
    ],
    ("on-warning", "warning-strong"),
]
# Things that must be seen but are not text (WCAG 1.4.11).
UI_PAIRS = [("line-strong", "surface"), ("accent", "surface"), ("danger-strong", "surface")]


def _tokens(block):
    text = CSS.read_text(encoding="utf-8")
    body = re.search(rf"/\* tokens:{block} \*/(.*?)/\* end tokens:{block} \*/", text, re.S)
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6});", body.group(1)))


def _luminance(hex_colour):
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a, b):
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize(("fg", "bg"), TEXT_PAIRS, ids=[f"{f}-on-{b}" for f, b in TEXT_PAIRS])
def test_text_contrast(mode, fg, bg):
    tokens = _tokens(mode)
    assert contrast(tokens[fg], tokens[bg]) >= 4.5, (mode, fg, bg)


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize(("fg", "bg"), UI_PAIRS, ids=[f"{f}-on-{b}" for f, b in UI_PAIRS])
def test_ui_contrast(mode, fg, bg):
    tokens = _tokens(mode)
    assert contrast(tokens[fg], tokens[bg]) >= 3, (mode, fg, bg)


def test_both_modes_define_every_token():
    assert _tokens("light").keys() == _tokens("dark").keys()


def test_phone_dark_mode_matches_the_chosen_dark_mode():
    """The prefers-color-scheme block repeats the dark values; keep them equal."""
    text = CSS.read_text(encoding="utf-8")
    media = re.search(r"@media \(prefers-color-scheme: dark\)\s*\{(.*?)\n\}", text, re.S).group(1)
    assert dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6});", media)) == _tokens("dark")


def test_templates_use_colour_tokens_only():
    """Raw palette classes (bg-white, text-slate-600...) would ignore dark mode."""
    root = Path(__file__).resolve().parents[3]
    raw = re.compile(
        r"(?<![\w-])(?:bg|text|border|divide)-(?:white|black|slate|gray|zinc|neutral|blue|red"
        r"|green|amber|yellow)(?:-\d+)?(?![\w-])"
    )
    files = [*(root / "templates").rglob("*.html"), *(root / "apps").rglob("forms.py")]
    found = {
        f"{p.relative_to(root)}: {m}" for p in files for m in raw.findall(p.read_text("utf-8"))
    }
    assert not found
