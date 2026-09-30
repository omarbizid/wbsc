"""HTML-to-text and name cleaning."""

from __future__ import annotations

import html
import re
import unicodedata

from bs4 import BeautifulSoup

_BLOCK_TAGS = ["p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "ul", "ol"]


def html_to_text(fragment: str | None) -> str:
    """Convert an HTML fragment (possibly entity-escaped, as Greenhouse returns it) to text.

    Block elements become line breaks so that list items stay separate, which matters
    for skill extraction ("Python" at the end of one bullet must not merge with the next).
    """
    if not fragment:
        return ""
    if "&lt;" in fragment and "<" not in fragment:
        fragment = html.unescape(fragment)
    soup = BeautifulSoup(fragment, "lxml")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    text = soup.get_text()
    text = unicodedata.normalize("NFKC", text).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    out, blank = [], False
    for ln in lines:
        if ln:
            out.append(ln)
            blank = False
        elif not blank and out:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def collapse_ws(s: str | None) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).strip()


_LEGAL_SUFFIX = re.compile(
    r"[,\s]+(ltd\.?|limited|plc|llp|llc|inc\.?|incorporated|gmbh|corp\.?|corporation|"
    r"co\.?|group\s+plc|uk\s+ltd)$",
    re.I,
)


def clean_company(name: str | None) -> str:
    """Display-clean company name: whitespace + legal suffixes removed, case preserved."""
    s = collapse_ws(name)
    prev = None
    while prev != s:
        prev = s
        s = _LEGAL_SUFFIX.sub("", s).strip(" ,.-")
    return s


def company_key(name: str | None) -> str:
    """Matching key for cross-source comparison (lowercase alphanumerics only)."""
    return re.sub(r"[^a-z0-9]", "", clean_company(name).lower())


_TITLE_NOISE = [
    re.compile(r"\((?:m|f|d|w|x)(?:\s*/\s*(?:m|f|d|w|x|div))+\)", re.I),   # (m/f/d)
    re.compile(r"\s*[-–|]\s*(?:hybrid|remote|on-?site)\s*$", re.I),
    re.compile(r"\s*\((?:hybrid|remote|on-?site)[^)]*\)\s*$", re.I),
]


def clean_title(title: str | None) -> str:
    s = collapse_ws(title)
    for rx in _TITLE_NOISE:
        s = rx.sub("", s).strip()
    return collapse_ws(s.strip(" -–|,"))
