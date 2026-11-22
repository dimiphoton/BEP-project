# Roadmap

Une case = une feature = une branche `feature/<nom>` = un tour d'autopilot.
Détails et critères dans `brief/specification.md`.

- [x] 1 — Socle : `docker-compose.yml` (Postgres 16), schémas `raw/staging/marts/ops`, rôles `ingest_rw` / `dbt_rw` / `reader_ro`, `.env.example`, `Makefile` (`up ingest build test`), dépendances dans `pyproject.toml`. Vérif : `make up` liste les schémas et les rôles.
- [x] 2 — `dim_municipality` : ingestion de la population par commune (clé `nis_code`), validation pydantic, quarantaine `ops.rejects` ; dbt staging, dimension et tests. Vérif : `make ingest build test` vert.
- [ ] 3 — Établissements (projet A) : ingestion BCE ou échantillon synthétique, `dim_enterprise`, `fact_establishment`, snapshot dbt, rattachement à la commune. Vérif : aucun établissement sans commune valide.
- [ ] 4 — Classification NACE par IA : famille d'activité en liste fermée, file de revue sous le seuil, évaluation (`make eval-nace`), journal `ops.ai_log`.
- [ ] 5 — Qualité et exploitation : `ops.run_log`, `scripts/healthcheck.py`, CI `.github/workflows/ci.yml` (ruff, pytest, Postgres éphémère, `dbt build`, IA en mode mock).
- [ ] 6 — Outillage des présentations : `scripts/export_metrics.py` (→ `docs/metrics.json`), `scripts/make_figures.py` (→ `pictures/presentations/`), `dbt docs generate` copié dans `docs/dbt/`, `scripts/check-slides.py` et son test.
- [ ] 7 — Présentation technique FR v1 (16–18 slides, projet A seul). `check-slides.py` vert et `scripts/build-slides.sh` sans erreur.
- [ ] 8 — Présentation recruteur FR v1 (12–14 slides). Mêmes contrôles.
- [ ] 9 — Marchés publics (projet B) : ingestion des avis, extraction IA structurée, `fact_public_contract`, lien par la commune, évaluation sur 10 avis.
- [ ] 10 — Lien par l'entreprise : résolution d'entités, `ops.review_queue`, `mart_contracts_by_municipality` ; mise à jour des 2 présentations FR.
- [ ] 11 — `README.md` (anglais, branche dédiée), `CHANGELOG.md`, `docs/decisions.md`, limites assumées et suite prévue (Airflow, CDC, alerting).
