# Journal de développement

## 2026-11-22 — Cadrage

- Identité, objectif et roadmap validés. Spécification dans `brief/specification.md`.
- `.cursor` retiré du suivi de `main` (il y était par erreur depuis le template).

## 2026-11-22 — Socle Postgres

- Docker Compose, Postgres 16, schémas `raw`, `staging`, `marts`, `ops`.
- Rôles `ingest_rw` (écrit `raw` et `ops`), `dbt_rw` (lit `raw`, écrit `staging` et `marts`), `reader_ro` (lit `marts`). Mots de passe dans `.env`.
- `make up` liste les schémas et les rôles. `make ingest`, `make build` et `make test` sont en place.
- Package renommé `observatory`. `dbt-core` est plafonné sous la 1.13, encore en bêta.

## 2026-11-22 — dim_municipality

- Population Statbel 2025 des 38 communes de la province de Namur (code INS `90000`), somme des cellules âge / sexe / nationalité / état civil.
- Upsert sur `nis_code` dans `raw.municipality_population`. Ligne invalide vers `ops.rejects`, le reste du fichier continue.
- dbt : `staging.stg_municipality`, `marts.dim_municipality`, tests `unique`, `not_null`, `accepted_values` et code INS de la province.
- Extrait versionné : `data/sample/statbel_population_namur_2025.csv`. Le zip complet reste dans `data/raw/`, hors git.
- Présentations non mises à jour : les decks FR sont les cases 7 et 8, et aucun chiffre ne s'écrit sans `docs/metrics.json` (case 6). Decks EN inchangés.

## 2026-11-22 — Établissements synthétiques

- La BCE Open Data demande un compte : pas de fichier anonyme, donc pas de parseur BCE. Échantillon `synthetic_establishments`, 300 établissements et 250 entreprises, codes INS réels des 38 communes.
- Upsert sur le numéro d'établissement et le numéro d'entreprise. Une commune inconnue ou une clé BCE fausse part dans `ops.rejects`.
- dbt : `dim_enterprise`, `fact_establishment`, snapshot `enterprise_snapshot` (stratégie check). Le test de relation vers `dim_municipality` passe : aucun établissement sans commune valide.
- `make ingest build test` vert (dbt PASS=53, pytest 24).
- Présentations non mises à jour (cases 7 et 8, pas encore de `docs/metrics.json`). Decks EN inchangés.

## 2026-11-22 — Famille d'activité NACE

- Règle sur les sections NACE univoques (industrie, construction, commerce, logistique, services). Les autres sections lisent le cache mock. `AI_MODE=live` s'arrête : aucun fournisseur, aucun format d'API inventé.
- Les 8 codes de l'échantillon sont tous décidés par la règle : 0 appel, 0 ligne en revue. Sous le seuil 0,8, la réponse va dans `ops.review_queue`. Chaque appel est ajouté à `ops.ai_log`.
- `make eval-nace` affiche `nace agreement 0.9800 (49/50); unverified labels 50; below threshold 7`. Les 50 libellés de `gold_nace.csv` ont `label_verified=false`. Le seul désaccord est le code 0729 (cache : industrie, fichier : autre, confiance 0,61, donc en revue).
- `make ingest build test` vert (dbt PASS=69, pytest 32).
- Présentations non mises à jour (cases 7 et 8, pas encore de `docs/metrics.json`). Decks EN inchangés.

## 2026-11-22 — Journal des passages et healthcheck

- Chaque étape de `make ingest` (communes, établissements, codes NACE) ouvre une ligne dans `ops.run_log` : début, fin, lignes lues, lignes refusées, statut. Pour les codes NACE, le volume suivi est le nombre de codes ; la file de revue n'est pas un rejet.
- `make healthcheck` affiche `ok`. Il échoue si le dernier passage n'est pas un succès, s'il a plus de 7 jours, ou si le volume gardé chute de plus de la moitié du succès précédent. Garder exactement la moitié passe encore.
- pytest 37. La CI (`.github/workflows/ci.yml`) enchaîne ruff, `make up`, ingest, dbt, pytest, `eval-nace` en `AI_MODE=mock`, puis le healthcheck. Elle n'a pas été observée sur GitHub : rien n'est poussé.
- Présentations non mises à jour (cases 7 et 8, pas encore de `docs/metrics.json`). Decks EN inchangés.
