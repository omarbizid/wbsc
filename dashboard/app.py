"""Streamlit dashboard for careers advisers.

Reads only the dbt `marts` schema (via jobintel.reporting). Run with:
    streamlit run dashboard/app.py
"""

from __future__ import annotations

from datetime import UTC, datetime

import altair as alt
import pandas as pd
import psycopg
import streamlit as st

from jobintel.reporting import data
from jobintel.reporting import metrics as m

st.set_page_config(page_title="UK Data Jobs", page_icon="📊", layout="wide")

VIEWS = ("Overview", "Skills", "Locations", "Salaries", "Trends", "Job explorer",
         "Data quality")
SAMPLE_NOTE = ("Counts are postings **observed in our collected sample** (company career "
               "sites and job boards we collect from), not a census of the UK job market.")
LINK = st.column_config.LinkColumn("Link", display_text="open ↗")
COLOR = "#2b6cb0"


# ------------------------------------------------------------------ data
@st.cache_data(ttl=300, show_spinner="Loading data…")
def get_marts() -> data.Marts:
    return data.load_marts()


def load_or_stop() -> data.Marts:
    try:
        return get_marts()
    except data.MartsNotBuilt:
        st.error("The reporting tables do not exist yet. Run `jobintel transform` "
                 "(dbt build), then reload this page.")
    except (psycopg.OperationalError, RuntimeError) as exc:
        st.error(f"Cannot reach the database: {exc}\n\nStart it with "
                 "`docker compose up -d postgres` and check DATABASE_URL in `.env`.")
    st.stop()


# ------------------------------------------------------------------ helpers
def fmt_ts(ts) -> str:
    return "—" if ts is None or pd.isna(ts) else f"{ts:%d %b %Y %H:%M} UTC"


def role_label(v: str) -> str:
    return m.ROLE_LABELS.get(v, v)


def hbar(df: pd.DataFrame, label: str, total: int, color: str | None = None,
         x_title: str | None = None) -> None:
    """Horizontal bars with 'n (pct%)' labels. `df` needs columns label, n, pct."""
    if df.empty or df["n"].sum() == 0:
        st.caption("No postings match the current filters.")
        return
    d = df.assign(text=[f"{n} ({p:.0f}%)" for n, p in zip(df["n"], df["pct"], strict=True)])
    enc = {"y": alt.Y(f"{label}:N", sort=None, title=None),
           "x": alt.X("n:Q", title=x_title or f"Postings (of {total})"),
           "tooltip": [alt.Tooltip(f"{label}:N", title="Value"),
                       alt.Tooltip("n:Q", title="Postings"),
                       alt.Tooltip("pct:Q", title=f"% of {total}", format=".1f")]}
    if color:
        enc["color"] = alt.Color(f"{color}:N", title=None)
    base = alt.Chart(d).encode(**enc)
    bars = base.mark_bar() if color else base.mark_bar(color=COLOR)
    text = base.mark_text(align="left", dx=3, color="#444").encode(
        text="text:N", color=alt.value("#444"))
    st.altair_chart((bars + text).properties(height=max(90, 26 * len(d))), width="stretch")


def postings_table(df: pd.DataFrame, extra: tuple[str, ...] = (), key: str | None = None,
                   height: int | str = "auto") -> None:
    """The traceability table: every aggregate drills down to rows like these."""
    if df.empty:
        st.caption("No postings.")
        return
    t = df.assign(
        city=df["cities"].apply(", ".join),
        role=df["role_category"].map(role_label),
        first_seen=df["first_seen_at"].dt.strftime("%Y-%m-%d"),
        last_seen=df["last_seen_at"].dt.strftime("%Y-%m-%d"),
        status=df["is_active"].map({True: "active", False: "inactive"}),
    )
    cols = ["title_raw", "company_clean", "city", "role", "seniority",
            "working_arrangement", *extra, "source_name", "first_seen", "last_seen",
            "status", "url"]
    st.dataframe(
        t[cols], hide_index=True, width="stretch", height=height, key=key,
        column_config={
            "title_raw": "Title", "company_clean": "Company", "city": "City",
            "role": "Role", "seniority": "Level", "working_arrangement": "Arrangement",
            "source_name": "Source", "first_seen": "First seen", "last_seen": "Last seen",
            "status": "Status", "url": LINK,
        },
    )


def drilldown(df: pd.DataFrame, dims: dict[str, str], key: str) -> None:
    """'Which postings are behind this number?' — pick a dimension and a value."""
    with st.expander("🔎 Show the postings behind these figures"):
        c1, c2 = st.columns(2)
        dim = c1.selectbox("Breakdown", list(dims), key=f"{key}_dim")
        col = dims[dim]
        values = sorted(df[col].fillna("unknown").unique())
        fmt = role_label if col == "role_category" else str
        val = c2.selectbox("Value", values, format_func=fmt, key=f"{key}_val")
        rows = df[df[col].fillna("unknown") == val]
        st.caption(f"{m.share(len(rows), len(df))} postings")
        postings_table(rows, key=f"{key}_tbl")


# ------------------------------------------------------------------ sidebar
def sidebar_filters(p: pd.DataFrame, sources: pd.DataFrame) -> m.Filters:
    sb = st.sidebar
    sb.header("Filters")
    roles_present = [r for r in m.ROLE_LABELS if r in set(p["role_category"])]
    roles = sb.multiselect(
        "Role category", roles_present,
        default=[r for r in m.TARGET_ROLES if r in roles_present],
        format_func=role_label,
        help="Defaults to the three target roles. Clear to include every role.")
    levels = sb.multiselect(
        "Seniority", [s for s in m.SENIORITY_ORDER if s in set(p["seniority"])],
        placeholder="All levels",
        help="Entry level = intern + entry. Most levels come from the job title; "
             "some are inferred from the description (see Job explorer).")
    all_cities = sorted({c for cs in p["cities"] for c in cs})
    cities = sb.multiselect("Location (city)", all_cities, placeholder="All locations",
                            help="'Unspecified' = no UK city named (e.g. 'United Kingdom').")
    arrangements = sb.multiselect("Working arrangement", list(m.ARRANGEMENTS),
                                  placeholder="All arrangements",
                                  help="Only from explicit statements; otherwise 'unknown'.")
    names = dict(zip(sources["source_id"], sources["display_name"], strict=True))
    srcs = sb.multiselect("Source", list(names), format_func=lambda s: names.get(s, s),
                          placeholder="All sources")

    lo, hi = p["first_seen_at"].min().date(), p["last_seen_at"].max().date()
    picked = sb.date_input("Observed between", value=(lo, hi), min_value=lo, max_value=hi,
                           help="Postings our collection saw at any time in this range.")
    start, end = (picked if isinstance(picked, tuple) and len(picked) == 2
                  else (lo, hi))
    active_only = sb.checkbox("Only postings still advertised", value=False,
                              help="Inactive = missing from 2 consecutive successful "
                                   "collections of its source.")
    unique = sb.checkbox("Count unique jobs (merge duplicates)", value=True,
                         help="The same job found on several sources counts once.")
    return m.Filters(tuple(roles), tuple(levels), tuple(cities), tuple(arrangements),
                     tuple(srcs), start, end, active_only, unique)


# ------------------------------------------------------------------ views
def view_overview(df: pd.DataFrame, all_postings: pd.DataFrame) -> None:
    n = len(df)
    entry = int(df["is_entry_level"].sum())
    c = st.columns(5)
    c[0].metric("Postings", n, help=f"{len(all_postings)} postings collected in total "
                                    "(all roles, all sources, before de-duplication).")
    c[1].metric("Still advertised", m.share(int(df["is_active"].sum()), n))
    c[2].metric("Entry level", m.share(entry, n))
    c[3].metric("Salary stated", m.share(int(df["has_salary"].sum()), n))
    c[4].metric("Arrangement stated",
                m.share(int((df["working_arrangement"] != "unknown").sum()), n))
    if n and entry < 20:
        st.info(f"Only **{entry}** entry-level postings match these filters. Treat "
                "entry-level percentages as indicative only.")

    left, right = st.columns(2)
    with left:
        st.subheader("Role category")
        hbar(m.breakdown(df, "role_category", tuple(m.ROLE_LABELS), m.ROLE_LABELS)
             .query("n > 0"), "label", n)
        st.subheader("Working arrangement")
        hbar(m.breakdown(df, "working_arrangement", m.ARRANGEMENTS), "label", n)
    with right:
        st.subheader("Seniority")
        hbar(m.breakdown(df, "seniority", m.SENIORITY_ORDER).query("n > 0"), "label", n)
        st.subheader("Source")
        hbar(m.breakdown(df, "source_name"), "label", n)
    drilldown(df, {"Role category": "role_category", "Seniority": "seniority",
                   "Working arrangement": "working_arrangement", "Source": "source_name"},
              key="ov")


def view_skills(df: pd.DataFrame, skills: pd.DataFrame) -> None:
    n = len(df)
    counts = m.skill_counts(skills, df)
    st.caption(f"Share of the **{n}** postings in the current filter whose description "
               "mentions each skill. A mention is not always a requirement. Extraction "
               "accuracy: see *docs/evaluation_report.md*.")
    if counts.empty:
        st.info("No skills found for the postings matching these filters.")
        return
    top = st.slider("Skills shown", 5, max(5, len(counts)), min(20, len(counts)))
    hbar(counts.head(top), "skill", n, color="skill_category")

    st.subheader("Skills that appear together")
    pairs = m.skill_pairs(skills, df)
    if pairs.empty:
        st.caption("No posting mentions two or more skills.")
    else:
        pairs["share"] = [m.share(k, n) for k in pairs["n"]]
        st.dataframe(pairs[["skill_a", "skill_b", "share"]], hide_index=True, width="stretch",
                     column_config={"skill_a": "Skill", "skill_b": "…with", "share":
                                    "Postings mentioning both"})

    with st.expander("🔎 Show the postings behind these figures", expanded=False):
        c1, c2 = st.columns(2)
        s1 = c1.selectbox("Skill", counts["skill"], key="sk1")
        s2 = c2.selectbox("…and also (optional)", ["—", *counts["skill"]], key="sk2")
        names = (s1,) if s2 in ("—", s1) else (s1, s2)
        rows = m.postings_with_skill(skills, df, *names)
        st.caption(f"{m.share(len(rows), n)} postings mention {' and '.join(names)}. "
                   "The evidence column shows the text that was matched.")
        postings_table(rows, extra=tuple(f"evidence: {s}" for s in names), key="sk_tbl")


def view_locations(df: pd.DataFrame) -> None:
    n = len(df)
    cities = m.city_counts(df)
    st.caption(f"Postings per city among **{n}** postings. A posting that names several "
               "cities counts in each, so bars can add up to more than the total. "
               "'Unspecified' means no UK city was named.")
    hbar(cities.head(25), "city", n)

    st.subheader("Working arrangement by city")
    if not cities.empty:
        top = cities.head(10)["city"].tolist()
        ex = (df[["posting_id", "cities", "working_arrangement"]]
              .explode("cities", ignore_index=True))
        ex = ex[ex["cities"].isin(top)]
        table = (pd.crosstab(ex["cities"], ex["working_arrangement"])
                 .reindex(index=top, columns=list(m.ARRANGEMENTS), fill_value=0))
        table["total"] = table.sum(axis=1)
        st.dataframe(table, width="stretch")

    with st.expander("🔎 Show the postings behind these figures"):
        if cities.empty:
            st.caption("No postings.")
        else:
            city = st.selectbox("City", cities["city"], key="loc_city")
            rows = m.postings_in_city(df, city)
            st.caption(f"{m.share(len(rows), n)} postings name {city}.")
            postings_table(rows, extra=("location_raw",), key="loc_tbl")


def view_salaries(df: pd.DataFrame) -> None:
    n = len(df)
    with_salary = df[df["has_salary"].astype(bool)]
    st.metric("Postings that state a salary", m.share(len(with_salary), n))
    st.caption("Only salaries written in the advert are used; nothing is estimated. "
               "Different currencies and pay periods are **never converted** and are "
               "reported separately. Each posting counts once, at the midpoint of its "
               "advertised range.")
    cov = (df.groupby("source_name")["has_salary"].agg(["sum", "count"]).reset_index())
    if not cov.empty:
        cov["coverage"] = [m.share(int(s), int(c)) for s, c in zip(cov["sum"], cov["count"],
                                                                    strict=True)]
        st.dataframe(cov[["source_name", "coverage"]], hide_index=True,
                     column_config={"source_name": "Source",
                                    "coverage": "Postings stating a salary"})
    groups = m.salary_groups(df)
    if groups.empty:
        st.info("No posting in the current filter states a salary.")
        return

    st.subheader("By currency and pay period")
    shown = groups.copy()
    for col in ("min", "p25", "median", "p75", "max"):
        shown[col] = shown[col].map(lambda v: "—" if pd.isna(v) else f"{v:,.0f}")
    st.dataframe(
        shown.drop(columns="enough_for_stats"), hide_index=True, width="stretch",
        column_config={"salary_currency": "Currency", "salary_period": "Per",
                       "n": "Postings", "n_period_inferred": st.column_config.NumberColumn(
                           "Period assumed", help="No period written; an amount ≥ 10,000 "
                           "was read as annual."),
                       "p25": "25th pct", "p75": "75th pct"})
    st.caption(f"Percentiles and median are withheld ('—') for groups with fewer than "
               f"{m.MIN_SALARIES_FOR_STATS} salaries.")

    options = [f"{c} per {p}" for c, p in zip(groups["salary_currency"],
                                              groups["salary_period"], strict=True)]
    pick = st.selectbox("Group", options, key="sal_group")
    cur, per = groups.iloc[options.index(pick)][["salary_currency", "salary_period"]]
    g = with_salary[(with_salary["salary_currency"] == cur)
                    & (with_salary["salary_period"] == per)].copy()
    g["midpoint"] = m.salary_midpoint(g)
    chart = alt.Chart(g).mark_bar(color=COLOR).encode(
        x=alt.X("midpoint:Q", bin=alt.Bin(maxbins=20), title=f"{cur} per {per} (midpoint)"),
        y=alt.Y("count():Q", title="Postings"))
    st.altair_chart(chart.properties(height=220), width="stretch")

    by_role = (g.groupby("role_category")["midpoint"].agg(["count", "median"]).reset_index()
               .sort_values("count", ascending=False))
    by_role["median"] = [f"{md:,.0f}" if c >= m.MIN_SALARIES_FOR_STATS else "—"
                         for c, md in zip(by_role["count"], by_role["median"], strict=True)]
    by_role["role_category"] = by_role["role_category"].map(role_label)
    st.dataframe(by_role, hide_index=True,
                 column_config={"role_category": "Role", "count": "Postings",
                                "median": "Median midpoint"})
    with st.expander("🔎 Show the postings behind these figures"):
        g = g.sort_values("midpoint", ascending=False)
        postings_table(g, extra=("salary_min", "salary_max", "salary_raw", "salary_source"),
                       key="sal_tbl")


def view_trends(df: pd.DataFrame, weeks: pd.DataFrame, f: m.Filters) -> None:
    st.caption("Postings **observed in our collected sample** in each week (Monday start). "
               "A change can reflect which sources and companies we collect from, not only "
               "the market. The first and last weeks may be incomplete.")
    by = st.radio("Split by", ["role_category", "seniority", "working_arrangement",
                               "source_name"], horizontal=True,
                  format_func=lambda c: c.replace("_", " ").capitalize())
    wk = m.weekly_counts(weeks, df, by=by, start=f.start, end=f.end)
    n_weeks = wk["week_start"].nunique()
    if n_weeks < 2:
        when = (f" (week of {wk['week_start'].min():%d %b %Y})" if n_weeks else "")
        st.info(f"Trends need at least two weeks of collection. There is data for "
                f"**{n_weeks}** week{'' if n_weeks == 1 else 's'}{when} so far. The chart "
                "fills in as daily collection continues.")
    if wk.empty:
        return
    if by == "role_category":
        wk[by] = wk[by].map(role_label)
    chart = alt.Chart(wk).mark_line(point=True).encode(
        x=alt.X("week_start:T", title="Week starting", axis=alt.Axis(format="%d %b")),
        y=alt.Y("n:Q", title="Postings observed"),
        color=alt.Color(f"{by}:N", title=None),
        tooltip=[alt.Tooltip("week_start:T", format="%d %b %Y"), by, "n"])
    st.altair_chart(chart.properties(height=320), width="stretch")

    st.subheader("Newly seen postings per week")
    st.caption("By the week our collection first saw each posting (employers' own "
               "publication dates are often missing).")
    new = m.new_per_week(df)
    st.altair_chart(alt.Chart(new).mark_bar(color=COLOR).encode(
        x=alt.X("week_start:T", title="Week starting", axis=alt.Axis(format="%d %b")),
        y=alt.Y("n:Q", title="Postings"), tooltip=["week_start:T", "n"]
    ).properties(height=200), width="stretch")

    with st.expander("🔎 Show the postings behind these figures"):
        options = sorted(wk["week_start"].unique(), reverse=True)
        week = st.selectbox("Week starting", options,
                            format_func=lambda d: f"{pd.Timestamp(d):%d %b %Y}", key="tr_wk")
        ids = weeks.loc[weeks["week_start"] == week, "posting_id"]
        rows = df[df["posting_id"].isin(ids)]
        st.caption(f"{m.share(len(rows), len(df))} postings observed that week.")
        postings_table(rows, key="tr_tbl")


def view_explorer(df: pd.DataFrame, all_postings: pd.DataFrame, skills: pd.DataFrame) -> None:
    q = st.text_input("Search title, company or location", placeholder="e.g. graduate, "
                      "Monzo, Manchester")
    rows = m.search(df, q).sort_values("last_seen_at", ascending=False)
    st.caption(f"{m.share(len(rows), len(df))} postings")
    postings_table(rows, key="ex_tbl", height=380)
    if rows.empty:
        return

    st.subheader("Posting details")
    labels = [f"{t} — {c} ({s}, #{i})" for t, c, s, i in
              zip(rows["title_raw"], rows["company_clean"], rows["source_name"],
                  rows["posting_id"], strict=True)]
    pick = st.selectbox("Posting", labels, key="ex_pick")
    r = rows.iloc[labels.index(pick)]
    st.markdown(f"### [{r.title_raw}]({r.url})\n**{r.company_clean}** · "
                f"{r.location_raw or '—'} · source: {r.source_name}")

    def fact(label, value, evidence=None):
        ev = f"  \n<small>evidence: “{evidence}”</small>" if evidence else ""
        st.markdown(f"**{label}:** {value}{ev}", unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        fact("Role", role_label(r.role_category), r.role_evidence)
        fact("Seniority", f"{r.seniority} (from {r.seniority_source})"
             if r.seniority_source and r.seniority_source != "none" else r.seniority,
             r.seniority_evidence)
        fact("Working arrangement", r.working_arrangement, r.arrangement_evidence)
        if r.has_salary:
            lo_hi = (f"{r.salary_min:,.0f}" if r.salary_min == r.salary_max
                     else f"{r.salary_min:,.0f}–{r.salary_max:,.0f}")
            fact("Salary", f"{lo_hi} {r.salary_currency} per {r.salary_period}"
                 + (" (period assumed)" if r.salary_period_inferred else ""), r.salary_raw)
        else:
            fact("Salary", "not stated")
    with c2:
        fact("Posted by employer", r.posted_date or "not stated by the source")
        fact("Seen by our collection", f"{fmt_ts(r.first_seen_at)} → {fmt_ts(r.last_seen_at)}"
             f" ({r.n_observations} collections, {r.n_versions} content versions)")
        fact("Status", "still advertised" if r.is_active else
             f"inactive since {fmt_ts(r.inactive_since)}")
        fact("Traceability", f"posting #{r.posting_id}, source id `{r.source_job_id}`, "
             f"scope `{r.scope_key}`, parser `{r.parser_version}`")

    sk = skills[skills["posting_id"] == r.posting_id]
    st.markdown("**Skills mentioned:** " + (", ".join(
        f"{s} (“{t}”)" for s, t in zip(sk["skill"], sk["matched_text"], strict=True))
        if not sk.empty else "none found"))
    members = m.cluster_members(all_postings, r.cluster_id)
    if len(members) > 1:
        st.markdown(f"**Duplicates:** this job was found {len(members)} times and is "
                    "counted once.")
        postings_table(members, key="ex_dup")


def view_quality(marts: data.Marts) -> None:
    st.caption("For advisers and maintainers: is the data complete and fresh?")
    st.subheader("Sources")
    h = marts.health.copy()
    for col in ("last_batch_at", "last_success_at"):
        h[col] = h[col].map(fmt_ts)
    st.dataframe(
        h[["display_name", "method", "last_batch_at", "last_batch_status", "last_success_at",
           "hours_since_success", "failed_batches_7d", "batches_7d", "open_quarantine",
           "active_postings", "total_postings", "last_batch_error"]],
        hide_index=True, width="stretch",
        column_config={"display_name": "Source", "method": "Method",
                       "last_batch_at": "Last collection", "last_batch_status": "Status",
                       "last_success_at": "Last success", "hours_since_success": "Hours since",
                       "failed_batches_7d": "Failed (7 d)", "batches_7d": "Runs (7 d)",
                       "open_quarantine": "Rejected records", "active_postings": "Active",
                       "total_postings": "Total", "last_batch_error": "Last error"})

    st.subheader("Possible duplicates not merged")
    st.caption("Postings that look alike but were **not** merged because the evidence was "
               "not strong enough. Each is counted separately.")
    u = marts.uncertain
    if u.empty:
        st.caption("None.")
    else:
        st.dataframe(u[["match_rule", "company_a", "title_a", "url_a", "company_b", "title_b",
                        "url_b", "primary_city"]], hide_index=True, width="stretch",
                     column_config={"url_a": LINK, "url_b": LINK, "match_rule": "Rule",
                                    "company_a": "Company A", "title_a": "Title A",
                                    "company_b": "Company B", "title_b": "Title B",
                                    "primary_city": "City"})

    st.subheader("Recent processing runs")
    lr = marts.load_runs.copy()
    lr["started_at"] = lr["started_at"].map(fmt_ts)
    st.dataframe(lr[["started_at", "source_id", "mode", "status", "batch_status",
                     "n_collected", "n_accepted", "n_rejected", "n_duplicate",
                     "n_out_of_scope", "n_new_postings", "duration_seconds", "parser_version"]],
                 hide_index=True, width="stretch", height=320)


# ------------------------------------------------------------------ page
def main() -> None:
    marts = load_or_stop()
    p = marts.postings
    view = st.sidebar.radio("View", VIEWS)
    st.sidebar.divider()
    if p.empty:
        st.title("UK entry-level data jobs")
        st.info("No postings yet. Run `jobintel collect --all` and `jobintel transform`.")
        st.stop()
    f = sidebar_filters(p, marts.health)
    df = m.apply_filters(p, f)

    st.title("UK entry-level data jobs")
    built = marts.health["marts_built_at"].max()
    st.caption(f"{SAMPLE_NOTE} Data refreshed {fmt_ts(built)}.")
    for s in m.stale_sources(marts.health, datetime.now(UTC)):
        st.warning("⚠️ Stale source — " + s.message)
    if df.empty and view != "Data quality":
        st.info("No postings match these filters. Widen them in the sidebar.")
        st.stop()

    st.header(view)
    if view == "Overview":
        view_overview(df, p)
    elif view == "Skills":
        view_skills(df, marts.skills)
    elif view == "Locations":
        view_locations(df)
    elif view == "Salaries":
        view_salaries(df)
    elif view == "Trends":
        view_trends(df, marts.weeks, f)
    elif view == "Job explorer":
        view_explorer(df, p, marts.skills)
    else:
        view_quality(marts)


main()
