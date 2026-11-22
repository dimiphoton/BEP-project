select
    notice_id,
    object_text,
    awarding_authority,
    lot_count,
    cpv_code,
    amount_eur,
    nis_code,
    winner_name,
    enterprise_number,
    confidence
from {{ source('raw', 'public_contract') }}
