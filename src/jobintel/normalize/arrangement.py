"""Working arrangement: remote / hybrid / on-site / unknown, from explicit statements only.

Decision rule (documented in docs/data_dictionary.md):
1. A structured hint from the source (e.g. a workplace-type field) wins.
2. Otherwise look at the location text, then the title, then the description.
   - Location/title: the words "remote", "hybrid" or "on-site"/"office-based" are enough.
   - Description: only phrases that describe *this role's* arrangement count, e.g.
     "fully remote", "this role is hybrid", "Location: London (Hybrid)". Benefit and
     culture phrases such as "30 days a year to work from anywhere", "remote-friendly
     approach to collaboration" or "on-site gym" do not count.
   Precedence inside one text: explicit negation of remote ("not a remote role") →
   on-site; remote offered → remote; hybrid → hybrid; on-site → on-site.
3. Otherwise "unknown". Nothing is inferred from the absence of a statement.
"""

from __future__ import annotations

import re

_NEG_REMOTE = re.compile(
    r"\b(?:not|no|isn'?t|cannot|can'?t)\s+(?:a\s+)?(?:fully\s+|100%\s+)?remote\b"
    r"(?!\s*-?\s*first)"
    r"|\bremote\s+(?:working\s+)?(?:is\s+)?not\s+(?:possible|available|offered)\b",
    re.I,
)

# --- short structured-ish texts (location field, title)
_LOC_REMOTE = re.compile(r"\bremote\b|\bwork\s+from\s+home\b|\bhome[- ]based\b", re.I)
_LOC_HYBRID = re.compile(r"\bhybrid\b", re.I)
_LOC_ONSITE = re.compile(r"\bon[- ]?site\b|\bin[- ]office\b|\boffice[- ]based\b", re.I)

# --- description: role-level statements only
_ROLE = r"(?:role|position|job|opportunity|vacancy|post)"
_LOCATION_LINE = re.compile(
    r"^\s*(?:location|work(?:ing)?\s+(?:location|pattern|arrangement|model)|workplace(?:\s+type)?"
    r"|work\s+type)\s*[:\-–]\s*(?P<line>[^\n]{0,120})$",
    re.I | re.M,
)
_DESC_REMOTE = re.compile(
    rf"\bfully[- ]remote\b|\b100%\s+remote\b|\bremote\s+{_ROLE}\b"
    rf"|\b(?:this|the)\s+{_ROLE}\s+(?:is|can\s+be)\s+(?:fully\s+|100%\s+)?"
    r"(?:remote|home[- ]based)\b"
    r"|\bwork\s+fully\s+remotely\b|\bremote\s*\((?:uk|united\s+kingdom)[^)]*\)"
    r"|\b(?:uk|united\s+kingdom)[- ]remote\b|\bremote\s*[-–]\s*(?:uk|united\s+kingdom)\b"
    r"|#LI-Remote\b",
    re.I,
)
# 1-4 office days a week is hybrid; 5 is on-site (see _DESC_ONSITE)
_DAYS = r"[1-4]\s*(?:(?:-|to)\s*[1-4])?\s*days?"
_DESC_HYBRID = re.compile(
    rf"\bhybrid\s+(?:{_ROLE}|working(?:\s+(?:model|pattern|arrangement))?)\b"
    rf"|\b(?:this|the)\s+{_ROLE}\s+is\s+hybrid\b|\(hybrid\b|#LI-\s?Hybrid\b"
    rf"|\b{_DAYS}\s+(?:a|per|each)\s+week\s+in\s+(?:the\s+|our\s+)?office\b"
    rf"|\b(?:in\s+(?:the\s+|our\s+)?office|on[- ]?site)\s+{_DAYS}\s+(?:a|per)\s+week\b",
    re.I,
)
_DESC_ONSITE = re.compile(
    rf"\bon[- ]?site\s+{_ROLE}\b|\boffice[- ]based\s+{_ROLE}\b"
    r"|\bfully\s+(?:office[- ]based|on[- ]?site)\b"
    rf"|\b(?:this|the)\s+{_ROLE}\s+is\s+(?:fully\s+)?(?:on[- ]?site|office[- ]based)\b"
    r"|\b5\s+days\s+(?:a|per)\s+week\s+in\s+(?:the\s+|our\s+)?office\b|#LI-Onsite\b",
    re.I,
)


def _snippet(text: str, m: re.Match, width: int = 60) -> str:
    a, b = max(0, m.start() - width), min(len(text), m.end() + width)
    return " ".join(text[a:b].split())


def _classify_short(text: str) -> tuple[str, str] | None:
    if not text:
        return None
    if _NEG_REMOTE.search(text):
        return "on-site", text
    for label, rx in (("remote", _LOC_REMOTE), ("hybrid", _LOC_HYBRID),
                      ("on-site", _LOC_ONSITE)):
        if rx.search(text):
            return label, " ".join(text.split())
    return None


def _classify_description(text: str) -> tuple[str, str] | None:
    if not text:
        return None
    # An explicit "Location: ..." line is treated like the location field.
    for m in _LOCATION_LINE.finditer(text):
        if r := _classify_short(m.group("line")):
            return r[0], _snippet(text, m, 0)
    if m := _NEG_REMOTE.search(text):
        return "on-site", _snippet(text, m)
    for label, rx in (("remote", _DESC_REMOTE), ("hybrid", _DESC_HYBRID),
                      ("on-site", _DESC_ONSITE)):
        if m := rx.search(text):
            return label, _snippet(text, m)
    return None


def classify_arrangement(
    *, hint: str | None = None, location: str | None = None, title: str | None = None,
    description: str | None = None,
) -> tuple[str, str | None]:
    """Return (arrangement, evidence snippet)."""
    if hint in {"remote", "hybrid", "on-site"}:
        return hint, f"source field: {hint}"
    for r in (_classify_short(location or ""), _classify_short(title or ""),
              _classify_description(description or "")):
        if r:
            return r
    return "unknown", None
