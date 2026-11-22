# Spécification technique — observatoire territorial (projets A + B)

## Sources

| Source | Usage | Si indisponible |
|---|---|---|
| BCE Open Data (entreprises, établissements, adresses, NACE ; compte requis) | projet A | 300 établissements synthétiques, vraies communes de la province |
| Statistiques communales (WalStat/IWEPS ou Statbel : code INS, population) | projet A | population synthétique, signalée |
| Avis de marchés (TED / portail wallon) | projet B | 10 à 15 avis synthétiques réalistes |

Échantillons versionnés dans `data/sample/` (petits). Données complètes dans
`data/raw/` (ignoré par git, jamais modifié sans confirmation). Les formats
et licences exacts ne sont pas vérifiés : tester un téléchargement avant de
s'engager, sinon synthétique.

## Modèle et architecture

```
sources -> ingestion Python (validation pydantic, quarantaine) -> Postgres raw -> dbt staging -> dbt marts
marts : dim_municipality (nis_code), dim_enterprise (enterprise_number), fact_establishment,
        fact_public_contract, mart_contracts_by_municipality
```

Deux liens entre A et B : par la **commune** (lieu d'exécution du marché vers
`nis_code`) et par l'**entreprise** (attributaire vers `enterprise_number`,
sinon rapprochement flou sur le nom avec validation humaine). Vérifier que
le numéro d'entreprise figure bien dans les avis ; sinon le lien par la
commune suffit comme version minimale.

## Exigences transverses

- Ingestion **idempotente** (upsert sur clé naturelle).
- **Dérive de schéma** : ligne invalide vers `ops.rejects` avec motif, flux non interrompu.
- **Sécurité** : trois rôles Postgres (`ingest_rw` écrit `raw` ; `dbt_rw` lit `raw` et écrit `staging`/`marts` ; `reader_ro` lit `marts`), secrets hors dépôt.
- **Monitoring** : `ops.run_log` (début, fin, source, lignes lues/rejetées, statut) ; `scripts/healthcheck.py` échoue si une source est périmée ou si le volume chute de plus de 50 %.
- **Historisation** : snapshot dbt sur `dim_enterprise`.
- **Qualité dbt** : `unique`, `not_null`, `relationships`, `accepted_values` + 2 tests métier (ex. code INS appartenant à la province de Namur ; montant de marché positif).

## Volet IA (3 volets, fournisseur interchangeable)

`AI_MODE=mock|live`, **défaut `mock`** avec réponses en cache dans
`ai/cache/*.json` : CI déterministe, sans clé. Chaque appel est tracé dans
`ops.ai_log` (entrée, sortie, modèle, version du prompt, date, confiance).

1. **Classification NACE vers famille d'activité** (liste fermée : industrie, logistique, commerce, services, construction, autre). Sous le seuil de confiance : `ops.review_queue`. Évaluation sur `data/eval/gold_nace.csv` (50 lignes, `label_verified=false` tant que l'utilisateur ne les a pas relues).
2. **Extraction des avis de marché** : schéma pydantic strict (objet, pouvoir adjudicateur, lots, code CPV, montant, commune d'exécution, attributaire, n° d'entreprise si présent). Sortie invalide : quarantaine. Évaluation sur 10 avis relus : exactitude par champ.
3. **Résolution d'entités** : normalisation + rapidfuzz ; seuil haut = lien automatique, zone grise = file de validation humaine, seuil bas = pas de lien.

Une métrique non mesurée reste « non mesuré » partout.

## `docs/metrics.json` (clés minimales)

`counts` (communes, établissements, entreprises, avis), `rejects` (par source),
`dbt` (tests réussis / échoués, depuis `target/run_results.json`),
`ai` (taux d'accord NACE, exactitude par champ d'extraction, ou `null`),
`data_origin` (par source : `real` ou `synthetic`), `generated_at`.

## `scripts/check-slides.py`

Lit `docs/presentations/*-fr.md` et `docs/metrics.json` ; sort en erreur si :

- le frontmatter n'est pas `marp: true` + `theme: portfolio` ;
- une classe `_class` n'est pas parmi `cover split full chart actions dark cta` ;
- le nombre de slides sort de 16–18 (technique) ou 12–14 (recruteur) ;
- il reste un `[...]` non suivi de `(`, ou `TBD`, `à compléter`, `à définir`, `lorem`, `TODO`, `{{`, `undefined`, `NaN`, ou un encodage cassé (`Ã©`, `Ã `, `â€`) ;
- une image référencée (non commentée) n'existe pas sur le disque, ou est une URL distante ;
- un nombre de 2 chiffres ou plus (hors années 2020–2030 et numéros de slide) est absent de `docs/metrics.json` et de `docs/presentations/numbers-allowlist.txt` ;
- un titre de slide est un libellé interdit (`Résultats`, `Méthodologie`, `Stack`, `Motivation`), ou une slide dépasse 70 mots ou 6 puces ;
- une source est synthétique (`data_origin`) et que la cover ou la slide « limites » ne dit pas « échantillon synthétique ».

## Définition de « terminé »

`make up ingest build test eval-nace` et `python scripts/check-slides.py`
passent sur une machine propre ; aucune valeur affichée qui ne vienne pas
d'une mesure ; tout élément synthétique ou non mesuré est signalé dans le
README et sur les présentations ; le README liste honnêtement ce qui n'est
pas fait.
