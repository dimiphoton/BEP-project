# Objectif du projet

- **But** : construire un mini socle de données unifié pour une intercommunale
  de développement économique de la Province de Namur. Deux sources sont
  intégrées dans un seul modèle : les établissements des parcs d'activités
  (projet A) et les avis de marchés publics (projet B), reliés par la commune
  (code INS) et par l'entreprise (numéro BCE).
- **Question fil rouge** : les marchés publics de l'intercommunale et des
  communes adhérentes profitent-ils aux entreprises installées dans les parcs
  d'activités de la province ?
- **Origine** : idée personnelle, préparée pour un entretien de Technical
  Business Analyst (département Digital). L'offre demande PostgreSQL, Python,
  dbt, DevOps, des flux entre applications et vers un Data Warehouse
  (orchestration, sécurité, monitoring), un Modèle de Données Unifié et un
  environnement orienté IA.
- **Contraintes de départ** : entretien le lundi 23/11/2026 à 15h ; démonstration
  sur échantillon, pas un système de production ; données indisponibles
  remplacées par des échantillons synthétiques explicitement étiquetés.

Second métier (une phrase) : BI, pour la question fil rouge.

Ce fichier capture le but brut. Les détails techniques sont dans
`brief/specification.md`, les dérogations au template dans
`.cursor/rules/06-projet-bep.mdc`.
