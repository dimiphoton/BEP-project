-- Échoue si un avis chargé a un montant nul ou négatif.
select
    notice_id,
    amount_eur
from {{ ref('fact_public_contract') }}
where amount_eur <= 0
