# Journal de développement

## 2026-11-22 — Cadrage

- Identité, objectif et roadmap validés. Spécification dans `brief/specification.md`.
- `.cursor` retiré du suivi de `main` (il y était par erreur depuis le template).

## 2026-11-22 — Socle Postgres

- Docker Compose, Postgres 16, schémas `raw`, `staging`, `marts`, `ops`.
- Rôles `ingest_rw` (écrit `raw` et `ops`), `dbt_rw` (lit `raw`, écrit `staging` et `marts`), `reader_ro` (lit `marts`). Mots de passe dans `.env`.
- `make up` liste les schémas et les rôles. `make ingest`, `make build` et `make test` sont en place.
- Package renommé `observatory`. `dbt-core` est plafonné sous la 1.13, encore en bêta.
