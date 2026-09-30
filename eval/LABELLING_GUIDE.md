# Skill labelling guide

This file defines how the evaluation labels in `labels_tune.yml` and `labels_eval.yml`
are produced. The labels are the ground truth used to measure the skill extractor.

## Sample
- Population: every posting currently in the database on 2026-09-25 (124 postings,
  Greenhouse + Lever). The latest version of each posting is used.
- Drawn with `random.Random(20260925).shuffle`: the first 20 are the **tune** set, the
  next 50 are the **eval** set (`sample_tune.jsonl`, `sample_eval.jsonl`).
- The tune set may be used to adjust the taxonomy and rules. The eval set is labelled
  before the extractor is run on it and is **not** used to change the rules. Any change
  made after looking at eval errors must be reported as such in the evaluation report.

## What to label
For each posting, list every skill from `config/skills.yml` (the defined list) that the
description **names as part of the role**: something the job uses, requires, prefers,
or that is part of the team's stated tech stack.

Rules:
1. **It must be named.** "Cloud platforms", "BI tools" or "a scripting language" do not
   count unless a product is named.
2. **Aliases count as the canonical skill.** Postgres → PostgreSQL; T-SQL / SSIS / SSRS →
   SQL Server; PySpark / Spark SQL → Spark; Google Cloud → GCP; Looker Studio → Looker;
   GitHub → Git; sklearn → scikit-learn.
3. **SQL** is labelled whenever SQL itself is named, including inside a named dialect or
   product (T-SQL, Spark SQL, SQL Server). It is not labelled for NoSQL, MySQL or
   PostgreSQL alone.
4. **Company or marketing mentions do not count**, e.g. "Databricks is the Data and AI
   company", or a product the employer sells that the role does not work with.
5. **Negated mentions do not count** ("no Python needed").
6. Mentions anywhere in the posting count if rules 1–5 hold, including "nice to have".
7. **R** only when it clearly refers to the R language.

## Who labelled
The labels were produced by the AI assistant (Claude) reading each full description,
before the extractor was run on that set. They have **not yet been reviewed by a person**.
The client's advisers should spot-check a sample. Any corrections go into the YAML
files, and `jobintel evaluate` is re-run.
