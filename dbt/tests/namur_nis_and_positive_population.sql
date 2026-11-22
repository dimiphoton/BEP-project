-- Échoue si un code INS sort de la province de Namur, ou si la population n'est pas positive.
select
    nis_code,
    province_nis_code,
    population
from {{ ref('dim_municipality') }}
where province_nis_code <> '90000'
   or nis_code !~ '^(91|92|93)[0-9]{3}$'
   or population <= 0
