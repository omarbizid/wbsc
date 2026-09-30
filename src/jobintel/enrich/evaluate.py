"""Measure skill extraction against the hand-labelled samples in eval/.

Precision = correct extracted skills / all extracted skills
Recall    = correct extracted skills / all labelled skills
Counted over (posting, skill) pairs ("micro" averages), plus a per-skill breakdown.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from jobintel.config import PROJECT_ROOT
from jobintel.enrich.skills import SkillExtractor, default_extractor

EVAL_DIR = PROJECT_ROOT / "eval"


@dataclass
class EvalResult:
    set_name: str
    extractor_version: str
    n_postings: int
    tp: int = 0
    fp: int = 0
    fn: int = 0
    per_skill: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    def to_dict(self) -> dict:
        return {
            "set": self.set_name, "extractor_version": self.extractor_version,
            "n_postings": self.n_postings, "tp": self.tp, "fp": self.fp, "fn": self.fn,
            "precision": round(self.precision, 4), "recall": round(self.recall, 4),
            "f1": round(self.f1, 4), "per_skill": self.per_skill, "errors": self.errors,
        }


def load_set(name: str, eval_dir: Path = EVAL_DIR) -> tuple[list[dict], dict[str, list[str]]]:
    rows = [json.loads(line) for line in
            (eval_dir / f"sample_{name}.jsonl").read_text(encoding="utf-8").splitlines() if line]
    labels = yaml.safe_load((eval_dir / f"labels_{name}.yml").read_text(encoding="utf-8"))
    return rows, labels


def evaluate(name: str, extractor: SkillExtractor | None = None,
             eval_dir: Path = EVAL_DIR) -> EvalResult:
    ex = extractor or default_extractor()
    rows, labels = load_set(name, eval_dir)
    unknown = {s for v in labels.values() for s in v} - set(ex.names)
    if unknown:
        raise ValueError(f"labels use skills not in the taxonomy: {sorted(unknown)}")
    missing = [r["id"] for r in rows if r["id"] not in labels]
    if missing:
        raise ValueError(f"postings without labels: {missing}")

    res = EvalResult(name, ex.version, len(rows))
    tp, fp, fn = Counter(), Counter(), Counter()
    for r in rows:
        hits = {h.skill: h for h in ex.extract(r["description"])}
        gold = set(labels[r["id"]])
        pred = set(hits)
        for s in pred & gold:
            tp[s] += 1
        for s in sorted(pred - gold):
            fp[s] += 1
            res.errors.append({"id": r["id"], "type": "FP", "skill": s,
                               "evidence": hits[s].snippet(r["description"])})
        for s in sorted(gold - pred):
            fn[s] += 1
            res.errors.append({"id": r["id"], "type": "FN", "skill": s})
    res.tp, res.fp, res.fn = sum(tp.values()), sum(fp.values()), sum(fn.values())
    for s in sorted(set(tp) | set(fp) | set(fn)):
        t, f, n = tp[s], fp[s], fn[s]
        res.per_skill[s] = {"tp": t, "fp": f, "fn": n,
                            "precision": round(t / (t + f), 3) if t + f else None,
                            "recall": round(t / (t + n), 3) if t + n else None}
    return res


def format_report(res: EvalResult) -> str:
    lines = [f"Set: {res.set_name} ({res.n_postings} postings), extractor {res.extractor_version}",
             f"TP={res.tp} FP={res.fp} FN={res.fn}  precision={res.precision:.3f} "
             f"recall={res.recall:.3f} F1={res.f1:.3f}", "", "Per skill (tp/fp/fn):"]
    for s, v in sorted(res.per_skill.items(), key=lambda kv: -(kv[1]["tp"] + kv[1]["fn"])):
        lines.append(f"  {s:<14} {v['tp']:>3}/{v['fp']:>2}/{v['fn']:>2}")
    if res.errors:
        lines.append("\nErrors:")
        for e in res.errors:
            ev = f"  «{e['evidence']}»" if "evidence" in e else ""
            lines.append(f"  {e['id']} {e['type']} {e['skill']}{ev}")
    return "\n".join(lines)
