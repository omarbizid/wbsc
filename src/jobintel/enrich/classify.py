"""Role category and seniority, derived from the job title (and, for seniority only,
explicit statements in the description when the title says nothing).

Role categories (first rule that matches wins):
  analytics_engineer  "analytics engineer/engineering"
  data_engineer       "data engineer/engineering", "data platform engineer", "ETL developer",
                      "<backend|software|platform> data engineer"
  data_scientist      "data scien…", "economist"  (adjacent role, kept separate)
  data_analyst        "data analyst", BI analyst/developer/engineer, insight(s)/reporting/MI/
                      product/marketing analyst, "<…> analytics manager/lead/analyst",
                      "head of analytics", "people analytics"
  other               clearly a different job (sales, solutions, ML/software/project
                      engineering, finance/risk/compliance/security/tax analysts…)
  unknown             a data-related title that fits none of the above
                      (e.g. "Finance Systems Data Assistant", "Data Manager")

Seniority (from the title first):
  intern     intern, internship, placement, summer analyst
  entry      graduate, junior/jr, entry-level, trainee, apprentice, associate, early careers
  manager    manager, head of, director, VP, chief
  lead       lead, principal, staff
  senior     senior/sr/snr, roman numerals III-IV
  mid        mid(-level), intermediate, roman numeral II
  If the title has no level: "entry" only when the description explicitly says
  graduate scheme/programme, entry-level, or no experience required; otherwise the
  minimum years of experience stated ("3+ years") maps 0-1 → entry, 2-4 → mid,
  5+ → senior. With no evidence: "unknown".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CLASSIFIER_VERSION = "classify-1"

ROLE_CATEGORIES = ("data_analyst", "data_engineer", "analytics_engineer", "data_scientist",
                   "other", "unknown")
SENIORITY_LEVELS = ("intern", "entry", "mid", "senior", "lead", "manager", "unknown")

_ROLE_RULES: list[tuple[str, re.Pattern]] = [
    ("analytics_engineer", re.compile(r"\banalytics\s+engineer(?:ing)?\b", re.I)),
    ("data_engineer", re.compile(
        r"\bdata\s+engineer(?:ing)?\b|\bdata\s+platform\s+engineer\b|\betl\s+(?:developer|engineer)\b"
        r"|\b(?:backend|software|platform|big)\s+data\s+engineer\b", re.I)),
    ("data_scientist", re.compile(r"\bdata\s+scien|\beconomist\b", re.I)),
    ("data_analyst", re.compile(
        r"\bdata\s+analyst\b|\bbi\s+(?:analyst|developer|engineer)\b|\bbusiness\s+intelligence\b"
        r"|\binsights?\s+analyst\b|\breporting\s+analyst\b|\bmi\s+analyst\b"
        r"|\bproduct\s+(?:data\s+)?analyst\b|\bmarketing\s+analyst\b|\bpeople\s+analytics\b"
        r"|\banalytics\s+(?:manager|lead|analyst)\b|\bhead\s+of\s+(?:\w+\s+)?analytics\b"
        r"|\bdata\s+(?:&|and)\s+analytics\b|\bgraduate\s+analyst\b|\bjunior\s+analyst\b", re.I)),
]
# Job families that stay "other" even when the title also contains a data word
# ("AI & Business Intelligence Program Manager", "Senior Regulatory Reporting Analyst").
_HARD_OTHER = re.compile(
    r"\bprogram(?:me)?\s+manager\b|\bproduct\s+manager\b|\bsolutions?\s+(?:architect|engineer)"
    r"|\bforward\s+deployed\b|\bsales\b|\baccount\s+(?:executive|manager)\b|\bregulatory\b"
    r"|\b(?:machine\s+learning|ml)\s+engineer|\bproject\s+engineer\b|\bclient\s+director\b"
    r"|\bcompliance\b|\bfinancial\s+reporting\b|\bdata\s+protection\b", re.I)
_OTHER = re.compile(
    r"\b(?:machine\s+learning|ml)\s+engineer|\bsolutions?\s+(?:architect|engineer)"
    r"|\bforward\s+deployed|\baccount\s+(?:executive|manager)|\bsales\b|\bsoftware\s+engineer"
    r"|\bproject\s+engineer|\bprogram(?:me)?\s+manager|\bproduct\s+manager|\bengineering\s+manager"
    r"|\b(?:tax|credit|risk|fraud|security|compliance|procurement|workforce|finance|financial"
    r"|fp&a|commercial|grid|power\s+grid|regulatory|capital\s+markets|hris|workday|anaplan"
    r"|business\s+systems|technical)\b[^,]*\banalyst\b"
    r"|\bcontroller\b|\bdirector\s+of\b(?!\s+data)|\btechnical\s+lead\s+manager\b"
    r"|\bvice\s+president\b|\bclient\s+director\b", re.I)
_DATA_WORD = re.compile(r"\bdata\b|\banalytics?\b|\bbi\b|\binsights?\b|\breporting\b", re.I)

_SENIORITY_TITLE: list[tuple[str, re.Pattern]] = [
    ("intern", re.compile(r"\bintern(?:ship)?\b|\bplacement\b|\bsummer\s+analyst\b", re.I)),
    ("entry", re.compile(
        r"\bgraduate\b|\bgrad\b|\bjunior\b|\bjr\.?\b|\bentry[- ]level\b|\btrainee\b"
        r"|\bapprentice(?:ship)?\b|\bearly\s+careers?\b"
        r"|\bassociate\b(?!\s+(?:director|partner|principal|vice|vp|manager|head))", re.I)),
    ("manager", re.compile(r"\bmanager\b|\bhead\s+of\b|\bdirector\b|\bvp\b|\bvice\s+president\b"
                           r"|\bchief\b", re.I)),
    ("lead", re.compile(r"\blead\b|\bprincipal\b|\bstaff\b", re.I)),
    # words are case-insensitive; roman numerals only in capitals ("iv" is not a level)
    ("senior", re.compile(r"(?i:\bsenior\b|\bsr\.?(?!\w)|\bsnr\b)|\b(?:III|IV)\b")),
    ("mid", re.compile(r"(?i:\bmid(?:[- ]level)?\b|\bintermediate\b)|\bII\b")),
]
_ENTRY_DESC = re.compile(
    r"\bgraduate\s+(?:scheme|programme|program|role|position|opportunity)\b|\bentry[- ]level\b"
    r"|\bno\s+(?:prior\s+|previous\s+)?(?:commercial\s+)?experience\s+(?:is\s+)?(?:required|needed|necessary)\b",
    re.I)
_YEARS = re.compile(
    r"\b(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*)?\+?\s*years?(?:'|’)?\s+(?:of\s+)?"
    r"(?:[\w/&-]+\s+){0,6}?experience\b", re.I)


@dataclass(frozen=True)
class Classification:
    role_category: str
    role_evidence: str | None
    seniority: str
    seniority_source: str      # title | description | none
    seniority_evidence: str | None


def classify_role(title: str) -> tuple[str, str | None]:
    if m := _HARD_OTHER.search(title):
        return "other", m.group(0)
    for category, rx in _ROLE_RULES:
        if m := rx.search(title):
            return category, m.group(0)
    if m := _OTHER.search(title):
        return "other", m.group(0)
    if m := _DATA_WORD.search(title):
        return "unknown", m.group(0)
    return "other", None


def classify_seniority(title: str, description: str | None = None
                       ) -> tuple[str, str, str | None]:
    for level, rx in _SENIORITY_TITLE:
        if m := rx.search(title):
            return level, "title", m.group(0)
    text = description or ""
    if m := _ENTRY_DESC.search(text):
        return "entry", "description", m.group(0)
    years = [int(m.group(1)) for m in _YEARS.finditer(text) if int(m.group(1)) <= 20]
    if years:
        y = min(years)
        level = "entry" if y <= 1 else "mid" if y <= 4 else "senior"
        return level, "description", f"{y}+ years experience"
    return "unknown", "none", None


def classify(title: str, description: str | None = None) -> Classification:
    role, role_ev = classify_role(title)
    level, source, level_ev = classify_seniority(title, description)
    return Classification(role, role_ev, level, source, level_ev)
