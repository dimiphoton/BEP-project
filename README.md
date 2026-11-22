# Territorial data observatory — Province of Namur

| | |
|---|---|
| **Role** | Data engineering |
| **Domain** | Economic development |
| **Stack** | ![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white) ![dbt](https://img.shields.io/badge/dbt-core-FF694B?logo=dbt&logoColor=white) ![Docker](https://img.shields.io/badge/Docker-compose-2496ED?logo=docker&logoColor=white) |
| **Level** | Intermediate |
| **Status** | Demo |

The Role · Domain · Stack line is filled from `brief/identite.md`.

## Objective

A small unified data platform for an intermunicipal economic-development
agency in the Province of Namur. Two sources land in one model:
business-park establishments and public-procurement notices, linked by
municipality (INS code) and, when the evidence is strong enough, by
enterprise (BCE number).

The question: do the agency's public contracts, and those of its member
municipalities, reach firms located in the province's business parks?

This repository is a demo on a sample. It is not a production warehouse.

## What was measured

Counts below are copied from [`docs/metrics.json`](docs/metrics.json)
(`generated_at` `2026-11-22T22:53:06+00:00`). Regenerate that file with
`make metrics` after a fresh `make ingest` and `make build`. Do not treat
a missing measure as zero: the file uses `null`.

| | |
|---|---|
| Municipalities (real Statbel extract) | 38 |
| Establishments / enterprises (synthetic) | 300 / 250 |
| Loaded public contracts (synthetic) | 10 |
| Contracts linked to a known enterprise | 8 |
| Contract names waiting for a human | 1 |
| Contract names with no link | 1 |
| Linked firms that also have a site in the execution municipality | 0 |
| NACE label agreement (draft labels) | 0.98 (49/50, none reviewed) |
| Contract field accuracy (draft labels) | 0.9875 (79/80, none reviewed) |
| dbt tests passed / failed | 88 / 0 |

The zero on the same municipality is a result, not a missing table. The
synthetic sites were placed on real Namur municipalities independently of
the notices, so a linked firm is in the province and still not in the
municipality where the contract is executed.

## Data

Municipality population is a real Statbel extract, reference year 2025:
[Population par lieu de résidence, nationalité, état civil, âge et sexe](https://statbel.fgov.be/fr/open-data/population-par-lieu-de-residence-nationalite-etat-civil-age-et-sexe-16)
(CC BY 4.0). The pipeline keeps province code `90000` and sums population
over age, sex, nationality and marital status, one row per `nis_code`.

The versioned extract is `data/sample/statbel_population_namur_2025.csv`.
When `data/raw/TF_SOC_POP_STRUCT_2025.zip` is present, `make ingest` uses
that file instead. The zip is not committed.

Establishments are `data/sample/synthetic_establishments.csv`, labelled
`synthetic_establishments`. BCE Open Data is not loaded: the official
download asks for an account
([BCE Open Data](https://kbopub.economie.fgov.be/kbo-open-data/login?lang=fr)).
Names, enterprise numbers and NACE codes in that file are generated. The
activity family is assigned afterwards.

Public-contract notices are `data/sample/synthetic_public_contracts.csv`,
labelled `synthetic_public_contracts`. No TED or Walloon portal file is
parsed: those formats were not read, and no API layout was invented. A
mock cache extracts each notice. A negative amount is quarantined. An
extraction under the confidence threshold waits in `ops.review_queue` and
is not loaded.

## How a notice meets a firm

A known enterprise number links at once. Otherwise the winner name is
normalised and compared with rapidfuzz. A high score links, a middle score
waits for a person, a low score does not link. `mart_contracts_by_municipality`
then counts, per execution municipality, how many linked firms also have
a site there.

NACE families (industrie, logistique, commerce, services, construction,
autre) use a rule when the NACE section has one family, and the mock cache
otherwise. `AI_MODE=mock` is the default. `AI_MODE=live` stops with an
error: no provider is configured. Gold files keep `label_verified=false`.

## Reproduce

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
make up
make ingest
make build
make test
make eval-nace
make eval-contracts
make healthcheck
```

`make up` creates `.env` from `.env.example` when needed, starts Postgres,
and prints the schemas and roles. Passwords in `.env.example` are for this
local demo only. If port 5432 is already used, change `POSTGRES_PORT` in
`.env` and run `make up` again.

The init script runs only when the Docker volume is first created. To
reapply it: `docker compose down -v`, then `make up`.

| Target | What it does |
|---|---|
| `make up` | Start Postgres and list schemas and roles |
| `make ingest` | Load municipalities, establishments, NACE families, notices, then enterprise links |
| `make build` | `dbt build` (models, snapshot, tests) |
| `make test` | `pytest` |
| `make eval-nace` | Score NACE families and append those calls to `ops.ai_log` |
| `make eval-contracts` | Score extracted contract fields and append those calls |
| `make healthcheck` | Fail if a monitored source is stale or its kept volume drops by more than half |
| `make metrics` | Rewrite `docs/metrics.json` from the database, dbt and the eval files |
| `make figures` | Write the presentation charts and copy them to `docs/slides-assets/` |
| `make dbt-docs` | Generate dbt docs and copy them to `docs/dbt/` |
| `make slides-check` | Check the French decks against `docs/metrics.json` |

## Limits of this demo

- Population is real and limited to the Province of Namur. Establishments
  and notices are synthetic and labelled as such.
- Agreement scores are not a validated accuracy. The gold labels were not
  reviewed (`label_verified=false`).
- Invalid rows go to `ops.rejects` for the latest run of that source, not
  as a permanent history. `ops.ai_log` is append-only. `ops.review_queue`
  is replaced per source on each run.
- `make healthcheck` watches pipeline runs (freshness and volume), not the
  statistical reference year.
- The CI workflow is in `.github/workflows/ci.yml` (ruff, Docker Compose
  Postgres, dbt, pytest, mock AI, healthcheck). It has not been observed
  on GitHub from this demo, because the branch was not pushed.
- French slide sources are `docs/presentations/presentation-*-fr.md`.
  The HTML committed under `docs/slides/` is still the portfolio template.
  GitHub Actions rewrites it on a push that touches the presentations.
  English decks were not written.
- `scripts/build-slides.sh` calls `npx`. On this machine the npm registry
  certificate check failed. The Marp CLI already installed locally did
  build the decks. Those HTML files were not committed.

## Not in this demo

Orchestration with Airflow, change-data capture, and alerting are the
production suite. Here, `ops.run_log`, `make healthcheck` and the CI
workflow stand in for them. Enterprise history is a dbt snapshot on name
and NACE code (check strategy), not a CDC stream.

## Repo structure

- `db/init/` — schemas and roles, applied on the first database start
- `data/sample/` — Statbel extract, synthetic establishments, synthetic notices
- `data/eval/` — draft NACE labels and draft contract fields
- `ai/` — prompts and mock caches
- `dbt/` — staging, marts, snapshot of `dim_enterprise`
- `src/observatory/` — CLI (`check`, `ingest`, `build`, `eval-nace`, `eval-contracts`)
- `scripts/healthcheck.py` — freshness and volume of the monitored sources
- `scripts/export_metrics.py`, `make_figures.py`, `check-slides.py` — measured numbers, charts, deck checks
- `docs/dbt/` — static dbt docs, including the contract mart (`make dbt-docs`)
- `docs/metrics.json` — measured counts, rejects, dbt tests, eval scores and links
- `.github/workflows/ci.yml` — ruff, ephemeral Postgres, dbt, pytest, mock AI
- `brief/` — scope and specification (French)
- `ROADMAP.md`, `JOURNAL.md`, `docs/decisions.md` — plan, log and choices (French)

## Presentations

French sources, Marp theme `portfolio`:

- [Recruiter (FR, markdown)](docs/presentations/presentation-recruteur-fr.md)
- [Technical (FR, markdown)](docs/presentations/presentation-technique-fr.md)

English decks are still the template. The HTML under `docs/slides/` is
regenerated by CI and is not the source of the decks.
