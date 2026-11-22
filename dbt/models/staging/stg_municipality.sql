-- Grain : une commune. Le fichier source est déjà filtré sur la province de Namur.
select
    nis_code,
    municipality_name,
    province_nis_code,
    population,
    reference_year
from {{ source('raw', 'municipality_population') }}
