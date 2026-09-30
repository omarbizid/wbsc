"""Rule-based skill extraction against the taxonomy in config/skills.yml.

How a match works:
1. Every alias pattern is wrapped in token boundaries: the characters immediately
   before and after the match must not be a letter, digit, "+", "#", "_" or "&".
   So "Java" does not match "JavaScript", "SQL" does not match "NoSQL"/"MySQL",
   "R" does not match "R&D", and "C" would not match "C++".
2. `case_sensitive` skills (Excel, Spark, Git, SQL, R, SAS...) only match in the casing
   of the pattern, because their lowercase forms are ordinary words.
3. A skill with `context` needs one of the context regexes within `context_window`
   characters (used for "R").
4. Former-employer lists are ignored: a hit is dropped when the text before it on the
   same line reads like "experience at <Company>" ("Prior experience at Databricks,
   Snowflake, AWS" names employers, not tools).
Each skill is reported at most once per posting, with its first valid match as evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from jobintel.config import PROJECT_ROOT

TAXONOMY_PATH = PROJECT_ROOT / "config" / "skills.yml"
_BOUNDARY_CHARS = r"A-Za-z0-9+#_&"
_EMPLOYER_LIST = re.compile(r"\b(?:experience|worked|background|time)\s+at\s+[A-Z]")


@dataclass(frozen=True)
class SkillHit:
    skill: str
    category: str
    matched_text: str
    start: int

    def snippet(self, text: str, width: int = 50) -> str:
        a, b = max(0, self.start - width), min(len(text), self.start + len(self.matched_text)
                                                + width)
        return " ".join(text[a:b].split())


@dataclass(frozen=True)
class _Skill:
    name: str
    category: str
    regex: re.Pattern
    context: tuple[re.Pattern, ...]
    context_window: int
    relaxed_regex: re.Pattern | None = None       # case-insensitive variant
    relaxed_context: tuple[re.Pattern, ...] = ()


class SkillExtractor:
    def __init__(self, taxonomy_path: Path = TAXONOMY_PATH):
        data = yaml.safe_load(Path(taxonomy_path).read_text(encoding="utf-8"))
        self.version: str = data["version"]
        self.skills: list[_Skill] = []
        for s in data["skills"]:
            flags = 0 if s.get("case_sensitive") else re.I
            alternation = "|".join(f"(?:{p})" for p in s["patterns"])
            wrapped = rf"(?<![{_BOUNDARY_CHARS}])(?:{alternation})(?![{_BOUNDARY_CHARS}])"
            ctx = tuple(re.compile(c, re.I) for c in s.get("context", []))
            relaxed = s.get("relaxed_case_context", [])
            self.skills.append(_Skill(
                s["name"], s["category"], re.compile(wrapped, flags), ctx,
                int(s.get("context_window", 40)),
                re.compile(wrapped, re.I) if relaxed else None,
                tuple(re.compile(c, re.I) for c in relaxed)))

    @property
    def names(self) -> list[str]:
        return [s.name for s in self.skills]

    def extract(self, text: str | None) -> list[SkillHit]:
        if not text:
            return []
        hits = []
        for skill in self.skills:
            if hit := self._first_valid(text, skill):
                hits.append(hit)
        return sorted(hits, key=lambda h: h.start)

    def _first_valid(self, text: str, skill: _Skill) -> SkillHit | None:
        candidates = [(m, True) for m in skill.regex.finditer(text)]
        if skill.relaxed_regex is not None:
            exact = {m.start() for m, _ in candidates}
            candidates += [(m, False) for m in skill.relaxed_regex.finditer(text)
                           if m.start() not in exact]
            candidates.sort(key=lambda c: c[0].start())
        for m, exact_case in candidates:
            if not exact_case and not self._near(text, m, skill.relaxed_context,
                                                 skill.context_window):
                continue
            if skill.context and not self._near(text, m, skill.context, skill.context_window):
                continue
            if self._in_employer_list(text, m.start()):
                continue
            return SkillHit(skill.name, skill.category, m.group(0), m.start())
        return None

    @staticmethod
    def _near(text: str, m: re.Match, patterns: tuple[re.Pattern, ...], window: int) -> bool:
        a = max(0, m.start() - window)
        around = text[a:m.end() + window]
        return any(c.search(around) for c in patterns)

    @staticmethod
    def _in_employer_list(text: str, pos: int) -> bool:
        line_start = max(text.rfind("\n", 0, pos), text.rfind("|", 0, pos)) + 1
        # include the hit's first character: the rule needs "at <Capital letter>"
        return bool(_EMPLOYER_LIST.search(text[line_start:pos + 1]))


@lru_cache(maxsize=1)
def default_extractor() -> SkillExtractor:
    return SkillExtractor()
