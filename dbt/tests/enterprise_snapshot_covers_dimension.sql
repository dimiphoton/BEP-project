-- Échoue si une entreprise de la dimension n'a pas de version ouverte dans le snapshot.
select
    enterprise.enterprise_number
from {{ ref('dim_enterprise') }} as enterprise
left join {{ ref('enterprise_snapshot') }} as snapshot_row
    on enterprise.enterprise_number = snapshot_row.enterprise_number
    and snapshot_row.dbt_valid_to is null
where snapshot_row.enterprise_number is null
