# Décisions

| Date | Décision | Alternative envisagée | Raison |
|---|---|---|---|
| 2026-11-22 | Package Python `observatory` | Garder le nom de template `mon_projet` | Le template demandait de renommer le package avant de coder. |
| 2026-11-22 | Trois rôles Postgres : `ingest_rw` (écrit `raw` et `ops`), `dbt_rw` (lit `raw`, écrit `staging` et `marts`), `reader_ro` (lit `marts`) | Un seul super-utilisateur pour tout le pipeline | Montrer qui a le droit d'écrire le brut, de transformer, et de lire. Les mots de passe restent dans `.env`, jamais dans le dépôt. |
| 2026-11-22 | `dbt-core` plafonné à `<1.13`, avec `dbt-postgres` 1.11 | Laisser pip installer `dbt-core` 1.13.0b1 | La 1.13 est encore en bêta. L'adaptateur Postgres 1.11 est stable. |
| 2026-11-22 | Population communale réelle : extrait Statbel 2025, province `90000`, somme des cellules | Population synthétique | Le zip officiel se télécharge (format pipe documenté sur la page Statbel). L'échantillon versionné est cet extrait. |
| 2026-11-22 | Schémas dbt `staging` et `marts` sans préfixe de cible | Laisser dbt créer `staging_marts` | Les rôles Postgres sont accordés sur les noms exacts créés au socle. |
| 2026-11-22 | 300 établissements synthétiques sur les communes réelles de Namur | Télécharger la BCE Open Data | Le portail officiel affiche un login : pas de fichier anonyme. On n'invente pas le format BCE. L'échantillon est nommé `synthetic_establishments`. |
| 2026-11-22 | Snapshot `enterprise_snapshot` en stratégie check, 250 entreprises pour 300 établissements | Stratégie timestamp, un établissement par entreprise | Le fichier n'a pas d'horodatage source. Le second site des 50 premières entreprises sépare le grain du fait de celui de la dimension. |
