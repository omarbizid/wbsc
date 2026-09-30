"""Advertised salary extraction.

Structured salary fields are normalised by `normalize_structured`. For free text,
`extract_salary_from_text` is deliberately conservative: it only accepts an amount
that is clearly pay (a range, or a single amount next to a pay keyword). It rejects
benefits such as "£1,000 a year for books", allowances, bonuses and OTE. If a
candidate is ambiguous, it returns nothing, so the salary stays NULL.

Pay period: taken from an explicit cue ("per annum", "per day", ...). When no cue is
present, an amount of at least 10,000 is treated as annual and flagged
`period_inferred=True`. Other amounts without a cue are rejected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR"}
CURRENCY_CODES = {"GBP", "USD", "EUR"}

_AMOUNT = r"(?:\d{1,3}(?:[,\s]\s?\d{3})+|\d+)(?:\.\d{1,2})?\s?[kK]?"
_CUR = r"(?:[£$€]|\b(?:GBP|USD|EUR)\s?)"
_RANGE_SEP = r"\s*(?:-|–|—|to)\s*"

_RANGE_RX = re.compile(
    rf"(?P<cur1>{_CUR})\s?(?P<a>{_AMOUNT})(?:{_RANGE_SEP})(?P<cur2>{_CUR})?\s?(?P<b>{_AMOUNT})",
    re.I,
)
_SINGLE_RX = re.compile(rf"(?P<cur1>{_CUR})\s?(?P<a>{_AMOUNT})", re.I)

_PERIOD_CUES = [
    ("year", re.compile(r"\b(?:per\s+annum|p\.?\s?a\.?|a\s+year|per\s+year|annual(?:ly)?"
                        r"|/\s?(?:yr|year))\b", re.I)),
    ("month", re.compile(r"\b(?:per\s+month|a\s+month|monthly|/\s?month|pcm)\b", re.I)),
    ("week", re.compile(r"\b(?:per\s+week|a\s+week|weekly|/\s?week)\b", re.I)),
    ("day", re.compile(r"\b(?:per\s+day|a\s+day|daily|day\s+rate|/\s?day|p/?d)\b", re.I)),
    ("hour", re.compile(r"\b(?:per\s+hour|an\s+hour|hourly|/\s?h(?:ou)?r|p/?h)\b", re.I)),
]
_PAY_CONTEXT = re.compile(
    r"\b(salary|salaries|base|pay|compensation|remuneration|package|paying|starting|"
    r"per\s+annum|p\.a\.)\b", re.I
)
# Amounts followed (or preceded) by these words are benefits, not salary.
_NOT_SALARY = re.compile(
    r"\b(budget|allowance|books|training|learning|conference|bonus|sign[- ]on|signing|"
    r"relocation|referral|stipend|premium|ote|on[- ]target|commission|voucher|"
    r"funding|revenue|raised|valuation|turnover|customers|users|million|billion|bn|"
    r"pension|contribution|wellbeing|equipment|home\s?office|holiday)\b", re.I
)

PLAUSIBLE = {  # inclusive bounds per period, in major currency units
    "year": (10_000, 500_000),
    "month": (800, 40_000),
    "week": (200, 10_000),
    "day": (80, 3_000),
    "hour": (5, 300),
}


@dataclass(frozen=True)
class Salary:
    min: Decimal | None
    max: Decimal | None
    currency: str | None
    period: str | None
    period_inferred: bool
    raw: str
    source: str  # "structured" | "text"


def _to_amount(s: str) -> Decimal:
    s = s.strip()
    k = s[-1] in "kK"
    s = re.sub(r"[,\s]", "", s.rstrip("kK"))
    v = Decimal(s)
    return v * 1000 if k else v


def _currency(tok: str) -> str:
    tok = tok.strip().upper()
    return CURRENCY_SYMBOLS.get(tok, tok if tok in CURRENCY_CODES else "GBP")


def _period_near(text: str, start: int, end: int) -> str | None:
    window = text[end:end + 45]
    for period, rx in _PERIOD_CUES:
        if rx.search(window):
            return period
    return None


def _plausible(v: Decimal, period: str) -> bool:
    lo, hi = PLAUSIBLE[period]
    return lo <= v <= hi


def extract_salary_from_text(text: str | None) -> Salary | None:
    if not text:
        return None
    candidates: list[tuple[re.Match, bool]] = []
    for m in _RANGE_RX.finditer(text):
        candidates.append((m, True))
    range_spans = [m.span() for m, _ in candidates]
    for m in _SINGLE_RX.finditer(text):
        if not any(a <= m.start() < b for a, b in range_spans):
            candidates.append((m, False))
    candidates.sort(key=lambda c: c[0].start())

    for m, is_range in candidates:
        before = text[max(0, m.start() - 40):m.start()]
        after = text[m.end():m.end() + 45]
        after_clause = re.split(r"[\n|.;]|\s[+➕]\s?", after, maxsplit=1)[0]
        before_clause = re.split(r"[\n|;]|\.\s", before)[-1]
        if _NOT_SALARY.search(after_clause) or _NOT_SALARY.search(before_clause[-25:]):
            continue
        if not is_range and not _PAY_CONTEXT.search(before_clause + " " + after_clause):
            continue
        try:
            a = _to_amount(m.group("a"))
            b = _to_amount(m.group("b")) if is_range else None
        except Exception:
            continue
        # "£121,600-164,600": second amount without symbol but same magnitude; "£50-60k"
        if is_range and m.group("b").strip()[-1:] in "kK" and a < 1000 <= b:
            a = a * 1000
        cur = _currency(m.group("cur1"))
        period = _period_near(text, m.start(), m.end())
        inferred = False
        if period is None:
            if a >= 10_000:
                period, inferred = "year", True
            else:
                continue
        lo, hi = (a, b) if b is not None else (a, a)
        if lo > hi:
            continue
        if not (_plausible(lo, period) and _plausible(hi, period)):
            continue
        raw = " ".join(text[m.start():m.end() + len(after_clause)].split())[:200]
        return Salary(min=lo, max=hi if is_range else lo, currency=cur, period=period,
                      period_inferred=inferred, raw=raw, source="text")
    return None


def normalize_structured(
    min_value, max_value, currency: str | None, period: str | None, raw: str | None = None,
) -> Salary | None:
    """Normalise a salary supplied in structured source fields. Returns None if absent."""
    def dec(v):
        if v in (None, "", 0, "0"):
            return None
        return Decimal(str(v))

    lo, hi = dec(min_value), dec(max_value)
    if lo is None and hi is None:
        return None
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    period_map = {
        "per annum": "year", "annum": "year", "annual": "year", "yearly": "year",
        "year": "year", "per year": "year", "per month": "month", "month": "month",
        "monthly": "month", "per week": "week", "week": "week", "weekly": "week",
        "per day": "day", "day": "day", "daily": "day", "per hour": "hour",
        "hour": "hour", "hourly": "hour",
    }
    p = period_map.get((period or "").strip().lower())
    # Currency is never assumed; a missing currency is caught by validation.
    return Salary(min=lo, max=hi, currency=currency.upper() if currency else None, period=p,
                  period_inferred=False, raw=raw or f"{lo}-{hi} {currency} {period}",
                  source="structured")
