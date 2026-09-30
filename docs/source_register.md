# Source register

Every source is documented here before it is implemented. It records who publishes the
data, what access is permitted, how we collect it, and the limits we apply. The rules for
all sources:

- Public or officially provided access only. No login walls, CAPTCHAs, paywalls or
  bypassing technical restrictions.
- We identify ourselves with an honest `User-Agent` (see `USER_AGENT` in `.env`).
- Requests have timeouts (20 s), bounded retries (3 retries, exponential backoff capped at
  60 s, `Retry-After` honoured) and a per-host minimum interval between requests.
- One scheduled collection per day. Raw responses are stored unchanged, so any
  reprocessing uses the saved copies and makes no new requests.
- A source is re-checked (robots.txt / terms) whenever it is modified, and at least
  every 3 months.

| ID | Source | Status | Method | Auth | Scope |
|----|--------|--------|--------|------|-------|
| `greenhouse` | Greenhouse Job Board API | **Active** (M1) | JSON API | none | curated company boards |
| `lever` | Lever-hosted career pages | **Active** (M2) | **HTML scraping** | none | curated company slugs |
| `reed` | Reed.co.uk Jobseeker API | Implemented (M2), **skipped until `REED_API_KEY` is set** | JSON API | API key (Basic auth) | keyword searches |

---

## S1 — Greenhouse Job Board API (`greenhouse`)

| | |
|---|---|
| Publisher | Greenhouse Software. Each board is published by the hiring company |
| Documentation | https://developers.greenhouse.io/job-board.html (now redirects to docs.greenhouse.io/job-board.html) |
| Access rules | The docs state: *"Job Board data is publicly available, so authentication is not required for any GET endpoints."* Only application submission (POST) needs a key, and we never use it. |
| Endpoint | `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true` |
| What we get | All open jobs on the board: id, title, location name, `absolute_url`, `first_published`, `updated_at`, `company_name`, `language`, HTML `content` (full description), departments, offices |
| Salary | Not a structured field in the list endpoint. It is extracted from the description text only when explicitly stated (see data dictionary) |
| Rate limits | None documented. We apply ≥ 1 s between requests. There is one request per board per day (23 boards → 23 requests/day) |
| Scope selection | `config/sources.yml`. Boards were chosen on 2026-09-22 by probing well-known UK employers' public boards for UK-located data-family titles |
| Identity | `source_job_id` = Greenhouse job `id` (stable per posting) |
| Filtering | Every job is stored raw. Only UK-located, English, data-family titles are loaded |
| Verified | 2026-09-22 |
| Known limits | Company boards carry only 0–11 UK data roles each and few entry-level ones. A board token can disappear if a company changes ATS, which is recorded as a failed scope (HTTP 404) |

## S2 — Lever-hosted career pages (`lever`)

| | |
|---|---|
| Publisher | Lever. Each page is published by the hiring company |
| Access rules | `https://jobs.lever.co/robots.txt` (checked 2026-09-22): `User-agent: * / Allow: / / Crawl-delay: 1` |
| Method | **HTML scraping** of the server-rendered listing page `https://jobs.lever.co/{company}` and each posting page `https://jobs.lever.co/{company}/{posting_id}` with BeautifulSoup. This source demonstrates HTML parsing (Lever also offers a JSON postings API, which we deliberately do not use here) |
| Rate limits | We honour `Crawl-delay: 1` (≥ 1 s between requests, sequential only). Posting pages are fetched only for listings whose title/location pass the scope pre-filter, which bounds requests to roughly tens per day |
| Companies | `config/sources.yml`: octoenergy, spotify, zopa, matillion, palantir. Chosen on 2026-09-25 by probing about 70 UK-relevant slugs (1 request/s). Most have no Lever page or no UK data roles |
| Page structure used | Listing: `div.posting` → `a.posting-title` (URL with posting UUID), `[data-qa=posting-name]`, `.location`, `.workplaceTypes`. Posting: `.posting-headline h2`, `.posting-categories .location/.department/.commitment/.workplaceTypes`, `div.section.page-centered` (description sections), `script[type=application/ld+json]` (schema.org JobPosting: `hiringOrganization.name`, `datePosted`, optional `baseSalary`) |
| Working arrangement | Lever's `workplaceTypes` label (Remote/Hybrid/On-site) is a structured field set by the employer and is used first |
| Structure changes | A posting page without `.posting-headline h2` is quarantined as `html_structure_changed` and never loaded half-parsed |
| Verified | 2026-09-25: first live run, 5 listing pages + 29 posting pages, 25 UK data postings loaded |
| Identity | `source_job_id` = the Lever posting UUID in the URL |
| Known limits | HTML structure can change without notice. The parser is covered by saved fixtures, and parse failures are quarantined |

## S3 — Reed.co.uk Jobseeker API (`reed`) — implemented, waiting for an API key

| | |
|---|---|
| Publisher | Reed.co.uk |
| Documentation | https://www.reed.co.uk/developers/jobseeker |
| Access rules | Official developer API. Free registration issues an API key, which is sent as the Basic-auth username with an empty password. The client registers and accepts Reed's API terms. `robots.txt` disallows `/api/` for *crawlers*. We are not crawling: we use the keyed API as intended by its terms. We never scrape reed.co.uk HTML pages |
| Endpoints | `GET /api/1.0/search?keywords=…&locationName=…&resultsToTake=100&resultsToSkip=…` then `GET /api/1.0/jobs/{jobId}` for the full description |
| What we get | jobId, employerName, jobTitle, locationName, minimumSalary, maximumSalary, currency, date, expirationDate, jobUrl, full description (details endpoint) |
| Rate limits | Not stated in the public docs. We apply ≥ 1 s between requests and a hard cap (`max_requests: 500` per run). If the cap is reached, the unfinished queries are recorded as **failed scopes**, so their postings are never treated as removed. We will record any limit Reed communicates on registration here |
| Field names | The docs list fields by human-readable name ("Job Id", "Salary Type"). The parser uses the camelCase keys (`jobId`, `jobTitle`, `employerName`, `locationName`, `minimumSalary`, `maximumSalary`, `currency`, `salaryType`, `datePosted`, `jobUrl`, `jobDescription`). **Tests currently use synthetic fixtures**; the first real response must be saved as a fixture and the keys checked |
| Salary | Structured: the advertised min/max + `salaryType` (per annum/day/hour…) + currency. Reed's `yearlyMinimumSalary` conversions are stored raw but not used, so we never mix in a conversion we have not documented |
| Scope | Keyword searches: "data analyst", "data engineer", "analytics engineer", "junior data analyst", "graduate data analyst", "BI analyst" |
| Identity | `source_job_id` = Reed `jobId` |
| Why this source | It is a UK aggregator and provides the volume of entry-level postings that company boards lack. It also gives a structured salary. Cross-source duplicates with company boards are expected and are matched (M3) |

## Rejected candidates

| Source | Reason |
|--------|--------|
| LinkedIn, Indeed, Glassdoor, Totaljobs HTML | Terms of service prohibit automated scraping; some need a login |
| Adzuna API | Permitted keyed API, but descriptions are truncated (~500 chars), which is too short for skill extraction. It is our fallback if Reed is unavailable |
| Workday career sites | Client-side rendered, and robots/terms differ per tenant. Not worth the risk for v1 |
