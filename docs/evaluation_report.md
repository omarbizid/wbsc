# Evaluation report: skill extraction and classification

*Status: Milestone 3, 2026-09-25. Extractor `skills-1`, classifier `classify-1`.*

## 1. Summary

| Set | Postings | Labelled skills | Precision | Recall | F1 |
|-----|---------:|----------------:|----------:|-------:|---:|
| **Eval (held out)** | **50** | **179** | **99.4 %** (178/179) | **99.4 %** (178/179) | **0.994** |
| Tune (used to adjust rules) | 20 | 59 | 100 % | 100 % | 1.000 |

The target was **≥ 90 % precision**, and the held-out set meets it. A test
(`tests/test_enrich.py::test_evaluation_meets_precision_target`) fails if a future
change drops eval precision below 90 %.

**Read these numbers with care.** They are probably optimistic (see §5). The labels were
made by the same AI assistant that wrote the rules, and have not yet been checked by a
person.

## 2. Method

- **Skill list:** 38 technical skills defined in `config/skills.yml` *before* labelling:
  languages, databases/warehouses, BI tools, transformation/orchestration, cloud,
  engineering tooling, Python ML libraries and statistics packages.
- **Sample:** all 124 postings in the database on 2026-09-25 (Greenhouse + Lever),
  shuffled with a fixed seed (`random.Random(20260925)`). The first 20 form the **tune**
  set and the next 50 the **eval** set. Files: `eval/sample_*.jsonl`.
- **Labelling:** each full description was read and every skill *named as part of the
  role* was recorded, following written rules (`eval/LABELLING_GUIDE.md`). Examples:
  aliases count, former employers don't, and "cloud platforms" without a product name
  doesn't count.
- **Separation:** the eval labels were written and **frozen with a checksum**
  (`eval/FROZEN.sha256`) before the extractor ever ran on the eval set. Rule changes were
  based only on the tune set and on design decisions made up front. The eval set was run
  once and nothing was changed afterwards.
- **Metric:** micro-averaged over (posting, skill) pairs. Precision = correct extracted /
  all extracted. Recall = correct extracted / all labelled.
- **Reproduce:** `jobintel evaluate eval` (`--save` writes `eval/results_eval_<version>.json`).

### Changes made on the tune set
| Observation (tune set) | Change |
|---|---|
| "e.g. spark, hadoop" written in lowercase was missed | Lowercase "spark" accepted only near other big-data words |
| "Apache Spark™" becomes "SparkTM" after text normalisation | Added the alias `SparkTM` |
| "…or R such as dplyr, caret" | Added R-ecosystem words to R's context list |
| "Prior experience at Databricks, Snowflake, AWS…" (employers, not tools) | Hits in a line that reads "experience at <Company>" are ignored |

## 3. Per-skill results (eval set)

| Skill | Correct | False + | Missed | | Skill | Correct | False + | Missed |
|---|---:|---:|---:|---|---|---:|---:|---:|
| SQL | 30 | 0 | 0 | | Kubernetes | 4 | 0 | 0 |
| Python | 29 | 0 | 0 | | R | 4 | 0 | 0 |
| dbt | 11 | 0 | 0 | | Snowflake | 4 | 0 | 0 |
| Looker | 10 | 0 | 0 | | Kafka | 3 | 0 | 0 |
| Spark | 10 | 0 | 0 | | Power BI | 3 | 0 | 0 |
| BigQuery | 9 | 0 | 0 | | Terraform | 3 | 0 | 0 |
| Tableau | 9 | 0 | 0 | | Excel | 3 | 0 | **1** |
| GCP | 8 | 0 | 0 | | Git, PostgreSQL, PyTorch, Redshift | 2 each | 0 | 0 |
| AWS | 7 | 0 | 0 | | Docker, Java, TensorFlow, pandas | 1 each | 0 | 0 |
| Airflow | 7 | 0 | 0 | | SAS | 0 | **1** | 0 |
| Databricks | 7 | 0 | 0 | | | | | |
| Azure | 5 | 0 | 0 | | | | | |

Skills not present in the eval sample (e.g. Qlik, VBA, SPSS, MongoDB) are **not
measured**. Their precision is unknown.

## 4. Errors and common failure types

| Posting | Type | What happened | Why |
|---|---|---|---|
| eval-08 | Missed Excel | "a good working knowledge of **excel**" | Excel is matched case-sensitively, so that "excel in this role" is not a skill. A lowercase product name is missed |
| eval-39 | False SAS | "sales experience in e-commerce, **SAS**, and other digital platforms" | The employer meant *SaaS*. The extractor reads the SAS statistics language |

Both error types are structural and will recur:
1. **Words that are also products** (Excel, Spark, Git, R, SAS). We trade some recall for
   precision with case-sensitivity and context rules.
2. **Typos and non-standard spellings** in the source text.

Other risks we know about but did not see in this sample:
- **Mentions that are not requirements.** Company self-description ("Databricks is the
  Data and AI company") or product lists. A Databricks job is correctly tagged Databricks
  because the role requires the platform, but a pure marketing mention would also match.
- **Negation** ("no Python needed") is not detected.
- **Skills outside the list** (e.g. Dagster, Fivetran, Lightdash, Streamlit, Jupyter,
  Google Sheets, Flink) are not extracted at all. The list must grow deliberately, with new
  labels.

## 5. Limitations of this evaluation

- **Same author for labels and rules.** Label and rule decisions may share blind spots.
  This inflates agreement. **Action: an adviser should re-label ~15 eval postings
  independently**. If agreement is lower, update the labels and re-run
  `jobintel evaluate eval`.
- **Sample composition.** All 70 labelled postings come from company careers pages
  (Greenhouse and Lever). They are mostly senior roles written in careful, explicit
  language. Reed adverts, which are aggregator-written and more often entry-level, may be
  noisier. **The evaluation must be repeated with Reed postings once that source is live.**
- **Small counts per skill.** Many skills have fewer than 5 labelled occurrences, so
  per-skill precision and recall are not reliable estimates.
- **Presence only.** We measure whether a skill is mentioned, not whether it is required
  or merely nice to have.

## 6. Role category and seniority

The rules are in `src/jobintel/enrich/classify.py`. They are tested with 26 unit cases
(`tests/test_enrich.py`). The output for all 124 current postings was reviewed by hand
(assistant review, 2026-09-25). That review fixed three bugs:
- "Senior" was not detected because of case-sensitivity.
- "AI & Business Intelligence *Program Manager*" was classified as a data analyst.
- "Associate Director" would have counted as entry level.

**No formal precision/recall has been measured for classification yet.** Known behaviour:

- Seniority comes from the title for 90 of 124 postings (73 %). 14 come from explicit
  description statements ("graduate scheme", "3+ years of experience"), and 20 remain
  `unknown`. The description-based levels are **inferred** and their evidence is stored in
  `seniority_evidence`.
- "Commercial / Credit / Risk / FP&A analyst" titles are classed as `other`, a
  deliberately narrow reading of *data analyst*. Titles that contain a data word but no
  clear family (e.g. "Finance Data Manager") are `unknown`.
- Mixed-level titles ("Mid and Senior Level") take the higher level.

**Current sample:** only **1** entry-level target-role posting (Zopa "2027 Graduate
Analyst"). Company careers pages advertise mostly senior roles. This confirms that the
Reed source is needed before entry-level findings can be reported.
