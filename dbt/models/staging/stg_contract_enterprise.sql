select
    notice_id,
    enterprise_number,
    method,
    score,
    status,
    winner_name
from {{ source('raw', 'contract_enterprise_link') }}
