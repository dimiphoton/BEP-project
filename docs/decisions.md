# Décisions

| Date | Décision | Alternative envisagée | Raison |
|---|---|---|---|
| 2026-11-22 | Package Python `observatory` | Garder le nom de template `mon_projet` | Le template demandait de renommer le package avant de coder. |
| 2026-11-22 | Trois rôles Postgres : `ingest_rw` (écrit `raw` et `ops`), `dbt_rw` (lit `raw`, écrit `staging` et `marts`), `reader_ro` (lit `marts`) | Un seul super-utilisateur pour tout le pipeline | Montrer qui a le droit d'écrire le brut, de transformer, et de lire. Les mots de passe restent dans `.env`, jamais dans le dépôt. |
| 2026-11-22 | `dbt-core` plafonné à `<1.13`, avec `dbt-postgres` 1.11 | Laisser pip installer `dbt-core` 1.13.0b1 | La 1.13 est encore en bêta. L'adaptateur Postgres 1.11 est stable. |
