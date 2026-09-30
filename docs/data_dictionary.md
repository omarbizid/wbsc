# Data dictionary

The reporting layer is the dbt `marts` schema. The dashboard reads only from `marts`.
Upstream tables (`core`, `ops`) are written by the Python pipeline.

## `marts.dim_postings`: one row per posting per source

| Column | Meaning |
|---|---|
| `posting_id` | Internal id of (source, source job id) |
| `source_id`, `source_name` | Where the posting was collected (`greenhouse`, `lever`, `reed`) |
| `source_job_id` | The source's own id for the posting |
| `scope_key` | The board / company / search query it was collected under |
| `url` | Link to the original posting |
| `title_raw`, `title_clean` | Title as published. The clean version has whitespace normalised and markers like "(m/f/d)" and " - Remote" removed |
| `company_raw`, `company_clean` | Company as published. The clean version has legal suffixes (Ltd, PLC…) removed |
| `location_raw` | Location text as published |
| `location_cities` | UK cities recognised in the location text (gazetteer) |
| `primary_city` | First city alphabetically, or `Unspecified` |
| `location_country` | `GB` if any UK place is named, else the first recognised country, else empty |
| `working_arrangement` | `remote` / `hybrid` / `on-site` / `unknown`, from explicit statements only (see below) |
| `arrangement_evidence` | The text the arrangement was taken from |
| `salary_min`, `salary_max` | Advertised pay, **only when explicitly stated**. A single figure fills both |
| `salary_currency` | ISO code (GBP, EUR, USD). Currencies are **never converted** |
| `salary_period` | `year` / `month` / `week` / `day` / `hour`. Never converted |
| `salary_period_inferred` | `true` when no period was written and an amount ≥ 10,000 was read as annual |
| `salary_source` | `structured` (a source field) or `text` (found in the description) |
| `salary_raw` | The text the salary was taken from |
| `has_salary` | A salary was advertised |
| `posted_date` | Date the employer published it, **only if the source provides it** |
| `role_category` | `data_analyst` / `data_engineer` / `analytics_engineer` / `data_scientist` / `other` / `unknown` (rules in `enrich/classify.py`) |
| `seniority` | `intern` / `entry` / `mid` / `senior` / `lead` / `manager` / `unknown` |
| `seniority_source`, `seniority_evidence` | `title`, `description` (inferred) or `none`, plus the matched text |
| `is_entry_level` | `seniority in (intern, entry)` |
| `is_target_role` | `role_category in (data_analyst, data_engineer, analytics_engineer)` |
| `first_seen_at`, `last_seen_at` | First and last time our collection observed it (UTC) |
| `n_observations`, `n_versions` | Number of collections it appeared in, and number of distinct content versions |
| `is_active` | See **inactive rule** |
| `n_successful_batches_missed`, `inactive_since` | Evidence for the inactive rule |
| `cluster_id`, `cluster_size`, `cluster_n_sources` | Duplicate cluster (see **duplicates**) |
| `is_canonical` | One posting per cluster. **Count unique jobs with `is_canonical`** |
| `current_version_id`, `parser_version` | Traceability to `core.posting_version` and the code that produced it |

## Other marts

| Table | Grain | Use |
|---|---|---|
| `fct_posting_skills` | posting × skill | Skills in the current version, with `matched_text` evidence |
| `fct_posting_weeks` | posting × ISO week (Monday) | Weeks in which a posting was observed, for trends |
| `mart_source_health` | source | Last batch/status/error, last success, `hours_since_success`, `is_stale`, failures in last 7 days, open quarantine, active postings, `marts_built_at` (when dbt last ran) |
| `mart_uncertain_matches` | pair of postings | Possible duplicates that were **not** merged, with a rule name and both URLs |
| `mart_load_runs` | load run | Collection log: mode, parser version, duration, collected/accepted/rejected/duplicate/out-of-scope counts |

## Derived rules

### Working arrangement
1. A structured source field (e.g. Lever "Hybrid") wins.
2. Otherwise, the location field, then the title, then role statements in the description
   ("this role is fully remote", "3 days a week in the office", "Location: London (Hybrid)",
   `#LI-Remote`). Benefit and culture phrases such as "30 days a year to work from anywhere",
   "remote-friendly approach" or "on-site gym" are ignored.
3. Precedence within one text: "not a remote role" → on-site; remote offered → remote;
   hybrid → hybrid; office-only → on-site.
4. Otherwise `unknown`.

### Salary
The value is used only when the advert states it. From text, only a range, or a single
amount next to a pay word ("salary", "base"…), is accepted. Amounts followed by benefit
words (budget, allowance, bonus, OTE…) are rejected, and so are implausible amounts per
period. Salaries in different currencies or periods are reported separately.

### Inactive rule
A posting is **inactive** once it has been absent from **2 consecutive successful
collections of its scope**. The scope is the same source and board/company/search query.
Failed or partial scopes never count as "absent", so a broken source cannot make postings
look removed. A posting that reappears becomes active again. Configure with
`inactive_after_missed_batches` in `dbt/dbt_project.yml`.

### Duplicates
- **Match group:** same normalised company (lowercase, alphanumerics, words like
  "group/ltd/plc/uk" removed), same normalised title (lowercase, punctuation and
  arrangement/location/contract words removed, bracketed text kept) and same primary city.
- **Likely duplicate (merged):** postings in a match group from **different sources**, or
  from the same source with an **identical description** (a re-post).
- **Not merged:** if one source has two different descriptions in the group, they are
  treated as separate openings, and the group is listed in `mart_uncertain_matches`
  (`same_title_different_description`).
- **Uncertain (listed, never merged):** same company and city with similar titles
  (identical level words, word overlap ≥ 0.6), or the same title with company names where
  one contains the other.
- **Canonical posting:** company careers source first, then earliest first seen.

### Skills
Skills are extracted from the description against `config/skills.yml` (38 skills). Aliases
map to canonical names (Postgres → PostgreSQL). Token boundaries prevent partial matches
(Java ≠ JavaScript, SQL ≠ NoSQL). Accuracy is in `docs/evaluation_report.md`.

### Dashboard counting rules
- **Unique jobs:** after the filters are applied, one posting is kept per duplicate cluster
  (the canonical posting if it passes the filters, otherwise the earliest seen). Filtering
  to one source therefore still counts that source's copy of a cross-source job.
- **Observation date range:** a posting is included if our collection saw it at some point
  in the range (first seen ≤ end and last seen ≥ start).
- **Cities:** a posting naming several cities counts once in each city.
- **Salaries:** one value per posting, the midpoint of the advertised range. Quartiles and
  median are only shown for groups of at least 5 salaries.
- **Stale source:** no successful collection in the last 36 hours, checked when the page
  is viewed (not when dbt ran).

### Trends
Weekly counts are **postings observed in our collected sample** during that week. They
are not market totals, and they depend on which sources and scopes were collected.
