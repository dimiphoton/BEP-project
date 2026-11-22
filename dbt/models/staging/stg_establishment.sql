select
    establishment_number,
    enterprise_number,
    establishment_name,
    nis_code,
    nace_code
from {{ source('raw', 'establishment') }}
