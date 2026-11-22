select
    enterprise_number,
    enterprise_name,
    nace_code
from {{ ref('stg_enterprise') }}
