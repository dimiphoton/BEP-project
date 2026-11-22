select
    nis_code,
    municipality_name,
    province_nis_code,
    population,
    reference_year
from {{ ref('stg_municipality') }}
