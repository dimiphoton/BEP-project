---
marp: true
theme: portfolio
paginate: true
---

<!-- _class: cover -->

# Un établissement sans commune valide peut-il entrer dans le mart ?

Data engineering · Développement économique · Python / PostgreSQL / dbt

Province de Namur · 2024-2026

Les établissements sont un échantillon synthétique.

---

<!-- _class: full -->

# Deux sources séparées ne répondent pas à la question.

L'intercommunale veut savoir où sont les sites.

Le code INS de la commune est le lien.

Sans lui, le parc et le territoire restent côte à côte.

---

<!-- _class: full -->

# Trois acteurs lisent le même modèle.

L'intercommunale prépare les parcs.

Les communes adhérentes portent les sites.

L'entreprise est le grain à reconnaître.

---

<!-- _class: full -->

# Une ligne part du fichier et arrive au modèle unifié.

La source est lue, puis validée.

Le brut reste brut.

dbt seul produit la commune, l'entreprise, l'établissement.

---

<!-- _class: actions -->

# Le flux tient en quatre gestes.

- Population communale réelle, une ligne par code INS
- Établissements : un échantillon synthétique
- Ligne invalide en quarantaine, le reste continue
- dbt relie le site à la commune déjà connue

---

<!-- _class: full -->

# La relation vers la commune est un test.

0 ligne refusée sur les deux chargements.

75 tests dbt réussissent.

0 test échoue.

---

<!-- _class: dark -->

# Dix avis sont rattachés à leur commune.

10 avis synthétiques ont une commune d'exécution.

Le lien avec l'entreprise n'est pas fait.

L'établissement, lui, reste sur sa commune.

---

<!-- _class: chart -->

# La population 2025 se lit commune par commune.

![h:460 Population communale](../slides-assets/municipality_population.png)

---

<!-- _class: full -->

# 300 établissements tiennent sur 38 communes.

250 entreprises portent ces sites.

Certaines en ont un second : le fait n'est pas la dimension.

Aucun site ne pointe hors du référentiel.

---

<!-- _class: chart -->

# La famille est déduite du code, pas observée sur le terrain.

![w:820 Familles d'activité](../slides-assets/establishments_by_family.png)

---

<!-- _class: full -->

# La BCE ne se télécharge pas sans compte.

Aucun parseur n'a été inventé pour un format non lu.

À la place, un échantillon synthétique, étiqueté comme tel.

Les codes INS, eux, viennent du fichier Statbel.

---

<!-- _class: full -->

# La règle classe. Le cache ne répond que dans le silence.

L'accord est de 0,98 sur 50 libellés.

49 concordent. Ces 50 libellés ne sont pas relus.

7 réponses sous le seuil vont en revue.

---

<!-- _class: full -->

# Le nom et le code NACE laissent une trace.

Le snapshot compare ces deux colonnes.

La source n'apporte pas d'horodatage.

On historise par contrôle, pas par une date inventée.

---

<!-- _class: full -->

# Ce qui a cassé a été corrigé, pas contourné.

Le schéma dbt ne préfixe plus les noms du socle.

Un Postgres local occupait déjà le port : le conteneur écoute à côté.

Le journal de passage retient le succès, pas seulement le fichier.

---

<!-- _class: dark -->

# Les limites tiennent en trois lignes.

Les établissements restent un échantillon synthétique.

Les 50 libellés de famille ne sont pas relus.

Les avis ne sont pas encore liés à une entreprise.

---

<!-- _class: actions -->

# Lundi, l'intercommunale pourrait s'en servir.

- Voir quelles communes concentrent les établissements
- Relire les réponses de famille encore en revue
- Rejouer un chargement sans doubler les sites
- Relier ensuite l'avis à l'entreprise, ce n'est pas fait

---

<!-- _class: cta -->

# On rejoue le socle, puis on lit la doc.

[Documentation dbt](../dbt/index.html)

[Dépôt](https://github.com/dimiphoton/BEP-project)

`make up`

`make ingest`

`make build`

`make test`

Python · PostgreSQL · dbt · Docker
