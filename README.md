# Territorial data observatory — Province of Namur

| | |
|---|---|
| **Role** | Data engineering |
| **Domain** | Economic development |
| **Stack** | ![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white) ![dbt](https://img.shields.io/badge/dbt-core-FF694B?logo=dbt&logoColor=white) ![Docker](https://img.shields.io/badge/Docker-compose-2496ED?logo=docker&logoColor=white) |
| **Level** | Intermediate |
| **Status** | In progress |

The Role · Domain · Stack line is filled from `brief/identite.md` at kickoff.

## Objective

A small unified data platform for an intermunicipal economic-development
agency in the Province of Namur. Two sources will land in one model:
business-park establishments and public-procurement notices, linked by
municipality (INS code) and enterprise (BCE number).

The question the platform is built to answer: do the agency's public
contracts, and those of its member municipalities, reach firms located in
the province's business parks?

## Data

Municipality population for the Province of Namur is a real Statbel extract,
reference year 2025: [Population par lieu de résidence, nationalité, état civil, âge et sexe](https://statbel.fgov.be/fr/open-data/population-par-lieu-de-residence-nationalite-etat-civil-age-et-sexe-16)
(CC BY 4.0). The pipeline keeps province code `90000` and sums population
over age, sex, nationality and marital status, one row per `nis_code`.

The versioned extract is `data/sample/statbel_population_namur_2025.csv`.
When `data/raw/TF_SOC_POP_STRUCT_2025.zip` is present, `make ingest` uses
that file instead. The full zip is not committed.

Establishments are a synthetic sample, `data/sample/synthetic_establishments.csv`,
labelled `synthetic_establishments`. BCE Open Data is not loaded: the
official download asks for an account
([BCE Open Data](https://kbopub.economie.fgov.be/kbo-open-data/login?lang=fr)).
The 300 sites use real Namur municipality codes from the Statbel extract.
Names, enterprise numbers and NACE codes in that file are generated, not
observed.

## Result

`dim_municipality` holds the Statbel 2025 population of the Province of Namur.
`dim_enterprise` and `fact_establishment` hold the synthetic establishments,
each tied to one of those municipalities. `enterprise_snapshot` keeps the
enterprise name and NACE code over time.

## Reproduce

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
make up
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
| `make ingest` | Load municipalities, then the synthetic establishments |
| `make build` | `dbt build` (models, snapshot, tests) |
| `make test` | `pytest` |

## Repo structure

- `db/init/` — schemas and roles, applied on the first database start
- `data/sample/` — Statbel municipality extract and `synthetic_establishments`
- `dbt/` — staging, marts, snapshot of `dim_enterprise`
- `src/observatory/` — CLI (`check`, `ingest`, `build`)
- `brief/` — scope and specification (French)
- `ROADMAP.md`, `JOURNAL.md` — plan and development log (French)

## Presentations

Two audiences × two languages (Marp theme `portfolio`, HTML on GitHub Pages).
The recruiter deck is a ~6-minute pitch; the technical deck is a ~12-minute
deep dive. They may diverge a lot — the bar is attractive and informative
for each audience, not a mirrored pair of slides.

- Recruiter and technical decks in English: coming soon.
- [Présentation grand public (FR)](docs/slides/presentation-recruteur-fr.html)
- [Présentation technique (FR)](docs/slides/presentation-technique-fr.html)
