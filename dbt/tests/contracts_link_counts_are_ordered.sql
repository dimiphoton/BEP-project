-- Un avis lié à un site de la même commune est d'abord un avis lié,
-- et un avis lié est d'abord un avis de la commune.
select
    nis_code,
    contract_count,
    linked_count,
    same_municipality_count
from {{ ref('mart_contracts_by_municipality') }}
where linked_count > contract_count
    or same_municipality_count > linked_count
