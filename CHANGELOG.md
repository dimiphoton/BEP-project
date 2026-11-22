# Changelog

## [Non publié]

- Initialisation du projet à partir du template portfolio.
- Socle Postgres 16 : schémas `raw`, `staging`, `marts`, `ops` et rôles `ingest_rw`, `dbt_rw`, `reader_ro`.
- Dimension `dim_municipality` : population Statbel 2025 des communes de la province de Namur, quarantaine `ops.rejects`.
- Établissements : échantillon `synthetic_establishments` (la BCE Open Data exige un compte), `dim_enterprise`, `fact_establishment`, snapshot dbt.
- Famille d'activité : règle sur les sections NACE univoques, cache mock sinon, file `ops.review_queue` sous le seuil, journal `ops.ai_log`, évaluation `make eval-nace` sur des libellés non relus.
- Exploitation : `ops.run_log`, `make healthcheck` (source périmée ou volume gardé en chute de plus de 50 %), CI avec Postgres éphémère et `AI_MODE=mock`.
- Outillage des présentations : `docs/metrics.json`, graphiques, documentation dbt, contrôle `scripts/check-slides.py`. Les decks eux-mêmes restent le squelette.
- Deck technique FR, projet A : question sur le rattachement à la commune, chiffres lus dans `docs/metrics.json`.
