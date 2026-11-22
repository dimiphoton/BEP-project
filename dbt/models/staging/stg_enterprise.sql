select
    enterprise_number,
    enterprise_name,
    nace_code
from {{ source('raw', 'enterprise') }}
