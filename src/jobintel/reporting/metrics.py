"""Filtering and aggregation for the dashboard: pandas in, pandas out, no Streamlit.

Every share is returned with its numerator *and* denominator so the UI can always show
"n of N". Figures describe postings in our collected sample, not the whole job market.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import combinations

import pandas as pd

TARGET_ROLES = ("data_analyst", "data_engineer", "analytics_engineer")
ROLE_LABELS = {
    "data_analyst": "Data analyst",
    "data_engineer": "Data engineer",
    "analytics_engineer": "Analytics engineer",
    "data_scientist": "Data scientist",
    "other": "Other",
    "unknown": "Unknown",
}
SENIORITY_ORDER = ("intern", "entry", "mid", "senior", "lead", "manager", "unknown")
ARRANGEMENTS = ("remote", "hybrid", "on-site", "unknown")

# Keep in step with dbt var `stale_after_hours` (dbt/dbt_project.yml).
STALE_AFTER_HOURS = 36
# Below this many salaries in a currency/period group we show values, not statistics.
MIN_SALARIES_FOR_STATS = 5


def share(n: int, total: int) -> str:
    """'12 of 40 (30%)' — never a bare percentage."""
    if total == 0:
        return f"{n} of 0"
    return f"{n} of {total} ({100 * n / total:.0f}%)"


# ------------------------------------------------------------------ filters
@dataclass(frozen=True)
class Filters:
    """Empty tuples mean 'no restriction'."""

    roles: tuple[str, ...] = ()
    seniorities: tuple[str, ...] = ()
    cities: tuple[str, ...] = ()
    arrangements: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    start: date | None = None
    end: date | None = None
    active_only: bool = False
    unique_jobs: bool = True


def apply_filters(postings: pd.DataFrame, f: Filters) -> pd.DataFrame:
    """Rows matching every filter. Date range = postings listed at some point in the range
    (first seen on/before `end` and last seen on/after `start`)."""
    df = postings
    mask = pd.Series(True, index=df.index)
    if f.roles:
        mask &= df["role_category"].isin(f.roles)
    if f.seniorities:
        mask &= df["seniority"].isin(f.seniorities)
    if f.arrangements:
        mask &= df["working_arrangement"].isin(f.arrangements)
    if f.sources:
        mask &= df["source_id"].isin(f.sources)
    if f.cities:
        wanted = set(f.cities)
        mask &= df["cities"].apply(lambda cs: bool(wanted.intersection(cs)))
    if f.start is not None:
        mask &= df["last_seen_at"].dt.date >= f.start
    if f.end is not None:
        mask &= df["first_seen_at"].dt.date <= f.end
    if f.active_only:
        mask &= df["is_active"].astype(bool)
    out = df[mask]
    return unique_jobs(out) if f.unique_jobs else out


def unique_jobs(df: pd.DataFrame) -> pd.DataFrame:
    """One posting per duplicate cluster *among the rows given*: the canonical one if it
    is present, otherwise the earliest seen. Applied after other filters so that e.g.
    filtering to one source still counts that source's copy of a cross-source job."""
    if df.empty:
        return df
    ordered = df.sort_values(["is_canonical", "first_seen_at", "posting_id"],
                             ascending=[False, True, True])
    return ordered.drop_duplicates("cluster_id").sort_index()


# ------------------------------------------------------------------ breakdowns
def breakdown(df: pd.DataFrame, column: str, order: tuple[str, ...] | None = None,
              labels: dict[str, str] | None = None) -> pd.DataFrame:
    """Counts per value with n, N and share. Values in `order` come first (zeros kept)."""
    total = len(df)
    counts = df[column].fillna("unknown").value_counts()
    values = list(order or ()) + [v for v in counts.index if v not in (order or ())]
    rows = [{"value": v, "label": (labels or {}).get(v, v), "n": int(counts.get(v, 0))}
            for v in values]
    out = pd.DataFrame(rows, columns=["value", "label", "n"])
    out["total"] = total
    out["pct"] = out["n"] / total * 100 if total else 0.0
    return out


def city_counts(df: pd.DataFrame) -> pd.DataFrame:
    """Postings per city. A posting naming several cities counts once in each, so the
    counts can add up to more than the number of postings."""
    total = len(df)
    if df.empty:
        return pd.DataFrame(columns=["city", "n", "total", "pct"])
    exploded = df[["posting_id", "cities"]].explode("cities")
    out = (exploded.groupby("cities")["posting_id"].nunique()
           .rename("n").reset_index().rename(columns={"cities": "city"})
           .sort_values(["n", "city"], ascending=[False, True], ignore_index=True))
    out["total"] = total
    out["pct"] = out["n"] / total * 100
    return out


def postings_in_city(df: pd.DataFrame, city: str) -> pd.DataFrame:
    return df[df["cities"].apply(lambda cs: city in cs)]


# ------------------------------------------------------------------ skills
def skill_counts(skills: pd.DataFrame, postings: pd.DataFrame) -> pd.DataFrame:
    """Number and share of the given postings that mention each skill."""
    total = len(postings)
    s = skills[skills["posting_id"].isin(postings["posting_id"])]
    if s.empty:
        return pd.DataFrame(columns=["skill", "skill_category", "n", "total", "pct"])
    out = (s.groupby(["skill", "skill_category"])["posting_id"].nunique()
           .rename("n").reset_index()
           .sort_values(["n", "skill"], ascending=[False, True], ignore_index=True))
    out["total"] = total
    out["pct"] = out["n"] / total * 100
    return out


def skill_pairs(skills: pd.DataFrame, postings: pd.DataFrame, top: int = 20) -> pd.DataFrame:
    """Skills that appear together in the same posting, most frequent first."""
    total = len(postings)
    s = skills[skills["posting_id"].isin(postings["posting_id"])]
    counter: dict[tuple[str, str], int] = {}
    for names in s.groupby("posting_id")["skill"].apply(lambda x: sorted(set(x))):
        for pair in combinations(names, 2):
            counter[pair] = counter.get(pair, 0) + 1
    rows = [{"skill_a": a, "skill_b": b, "n": n} for (a, b), n in counter.items()]
    out = pd.DataFrame(rows, columns=["skill_a", "skill_b", "n"])
    out = out.sort_values(["n", "skill_a", "skill_b"], ascending=[False, True, True],
                          ignore_index=True).head(top)
    out["total"] = total
    out["pct"] = out["n"] / total * 100 if total else 0.0
    return out


def postings_with_skill(skills: pd.DataFrame, postings: pd.DataFrame,
                        *names: str) -> pd.DataFrame:
    """Postings mentioning *all* the given skills, with the matched text as evidence."""
    df = postings
    for name in names:
        hits = skills.loc[skills["skill"] == name, ["posting_id", "matched_text"]]
        hits = hits.rename(columns={"matched_text": f"evidence: {name}"})
        df = df.merge(hits, on="posting_id", how="inner")
    return df


# ------------------------------------------------------------------ salaries
def salary_groups(df: pd.DataFrame) -> pd.DataFrame:
    """Advertised salaries per (currency, period). Never converted between groups.
    The value per posting is the midpoint of the advertised range (a single figure is
    its own midpoint). Statistics are withheld (NaN) for groups smaller than
    MIN_SALARIES_FOR_STATS."""
    cols = ["salary_currency", "salary_period", "n", "n_period_inferred",
            "min", "p25", "median", "p75", "max", "enough_for_stats"]
    s = df[df["has_salary"].astype(bool)].copy()
    if s.empty:
        return pd.DataFrame(columns=cols)
    s["midpoint"] = salary_midpoint(s)
    rows = []
    for (cur, per), g in s.groupby(["salary_currency", "salary_period"], dropna=False):
        mid = g["midpoint"]
        enough = len(g) >= MIN_SALARIES_FOR_STATS
        p25, median, p75 = ([float(mid.quantile(q)) for q in (0.25, 0.5, 0.75)] if enough
                            else [float("nan")] * 3)
        rows.append({
            "salary_currency": cur, "salary_period": per, "n": len(g),
            "n_period_inferred": int(g["salary_period_inferred"].fillna(False).sum()),
            "min": float(mid.min()), "p25": p25, "median": median, "p75": p75,
            "max": float(mid.max()), "enough_for_stats": enough,
        })
    return (pd.DataFrame(rows, columns=cols)
            .sort_values("n", ascending=False, ignore_index=True))


def salary_midpoint(df: pd.DataFrame) -> pd.Series:
    return df[["salary_min", "salary_max"]].mean(axis=1, skipna=True)


# ------------------------------------------------------------------ trends
def weekly_counts(weeks: pd.DataFrame, postings: pd.DataFrame, by: str = "role_category",
                  start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """Postings observed per ISO week (Monday), split by `by`. Weeks that only partly
    overlap the date range are kept, so the first/last week may be incomplete."""
    w = weeks[weeks["posting_id"].isin(postings["posting_id"])]
    if start is not None:
        w = w[w["week_start"].dt.date + timedelta(days=6) >= start]
    if end is not None:
        w = w[w["week_start"].dt.date <= end]
    w = w.merge(postings[["posting_id", by]], on="posting_id")
    if w.empty:
        return pd.DataFrame(columns=["week_start", by, "n"])
    return (w.groupby(["week_start", by])["posting_id"].nunique().rename("n")
            .reset_index().sort_values(["week_start", by], ignore_index=True))


def new_per_week(postings: pd.DataFrame) -> pd.DataFrame:
    """Postings by the week our collection *first* saw them (not the employer's date)."""
    if postings.empty:
        return pd.DataFrame(columns=["week_start", "n"])
    wk = postings["first_seen_at"].dt.tz_convert(None).dt.to_period("W-SUN").dt.start_time
    return (wk.value_counts().rename("n").rename_axis("week_start").reset_index()
            .sort_values("week_start", ignore_index=True))


# ------------------------------------------------------------------ freshness
@dataclass(frozen=True)
class StaleSource:
    source_id: str
    name: str
    last_success_at: datetime | None
    hours_since_success: float | None

    @property
    def message(self) -> str:
        if self.last_success_at is None:
            return (f"**{self.name}**: no successful collection yet, so it contributes no "
                    f"postings.")
        return (f"**{self.name}**: last successful collection "
                f"{self.last_success_at:%d %b %Y %H:%M} UTC "
                f"({self.hours_since_success:.0f} h ago). Its postings may be out of date.")


def stale_sources(health: pd.DataFrame, now: datetime,
                  after_hours: float = STALE_AFTER_HOURS) -> list[StaleSource]:
    """Sources whose last successful collection is older than `after_hours` (or never).
    Computed against `now`, not the time the marts were built."""
    out = []
    for r in health.itertuples(index=False):
        last = None if pd.isna(r.last_success_at) else r.last_success_at.to_pydatetime()
        hours = None if last is None else (now - last).total_seconds() / 3600
        if last is None or hours > after_hours:
            out.append(StaleSource(r.source_id, r.display_name, last, hours))
    return out


# ------------------------------------------------------------------ explorer
def search(df: pd.DataFrame, text: str) -> pd.DataFrame:
    """Case-insensitive substring search over title, company and location."""
    text = (text or "").strip().lower()
    if not text:
        return df
    hay = (df["title_raw"].fillna("") + " " + df["company_clean"].fillna("") + " "
           + df["location_raw"].fillna("")).str.lower()
    return df[hay.str.contains(text, regex=False)]


def cluster_members(postings: pd.DataFrame, cluster_id: int) -> pd.DataFrame:
    """All postings (any source, unfiltered) merged into one duplicate cluster."""
    return postings[postings["cluster_id"] == cluster_id]
