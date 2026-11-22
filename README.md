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

No source extract is loaded yet. Planned coverage: Province of Namur,
sample years 2024–2026. If a public file cannot be downloaded, a later
step will switch to a synthetic sample labelled `synthetic_*`.

## Result

PostgreSQL 16 is up with schemas `raw`, `staging`, `marts` and `ops`, and
three roles (`ingest_rw`, `dbt_rw`, `reader_ro`). Ingestion and marts come
in the next steps. `dbt build` runs, with no model yet.

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
| `make ingest` | Check that `ingest_rw` can write `raw` and `ops` |
| `make build` | `dbt build` (no model at this step) |
| `make test` | `pytest` |

## Repo structure

- `db/init/` — schemas and roles, applied on the first database start
- `dbt/` — dbt project (models arrive with the municipality dimension)
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
