"""Write skills and classifications for posting versions.

`enrich_versions` is called by the loader for versions it touches, and by
`jobintel enrich` to (re)compute every version whose stored extractor/classifier
version differs from the current code. Re-running is idempotent.
"""

from __future__ import annotations

import psycopg

from jobintel.enrich.classify import CLASSIFIER_VERSION, classify
from jobintel.enrich.skills import SkillExtractor, default_extractor


def stale_version_ids(conn: psycopg.Connection, extractor: SkillExtractor | None = None,
                      force: bool = False) -> list[int]:
    ex = extractor or default_extractor()
    if force:
        rows = conn.execute("select version_id from core.posting_version order by 1")
    else:
        rows = conn.execute(
            """select v.version_id from core.posting_version v
               left join core.version_classification c using (version_id)
               where c.version_id is null or c.classifier_version <> %s
                  or c.extractor_version <> %s
               order by 1""", (CLASSIFIER_VERSION, ex.version))
    return [r[0] for r in rows]


def enrich_versions(conn: psycopg.Connection, version_ids: list[int],
                    extractor: SkillExtractor | None = None) -> int:
    """(Re)compute skills and classification for the given versions. Returns the count."""
    if not version_ids:
        return 0
    ex = extractor or default_extractor()
    rows = conn.execute(
        """select version_id, title_clean, description_text from core.posting_version
           where version_id = any(%s)""", (version_ids,)).fetchall()
    for version_id, title, description in rows:
        conn.execute("delete from core.version_skill where version_id = %s", (version_id,))
        for hit in ex.extract(description):
            conn.execute(
                """insert into core.version_skill
                     (version_id, skill, skill_category, matched_text, extractor_version)
                   values (%s, %s, %s, %s, %s)""",
                (version_id, hit.skill, hit.category, hit.matched_text, ex.version))
        c = classify(title, description)
        conn.execute(
            """insert into core.version_classification
                 (version_id, role_category, role_evidence, seniority, seniority_source,
                  seniority_evidence, classifier_version, extractor_version)
               values (%s, %s, %s, %s, %s, %s, %s, %s)
               on conflict (version_id) do update set
                 role_category = excluded.role_category, role_evidence = excluded.role_evidence,
                 seniority = excluded.seniority, seniority_source = excluded.seniority_source,
                 seniority_evidence = excluded.seniority_evidence,
                 classifier_version = excluded.classifier_version,
                 extractor_version = excluded.extractor_version""",
            (version_id, c.role_category, c.role_evidence, c.seniority, c.seniority_source,
             c.seniority_evidence, CLASSIFIER_VERSION, ex.version))
    return len(rows)
