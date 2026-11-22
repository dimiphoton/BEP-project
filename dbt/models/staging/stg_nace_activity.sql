-- Famille d'activité déposée par le classeur Python, une ligne par code NACE.
select
    nace_code,
    activity_family,
    method,
    confidence
from {{ source('raw', 'nace_activity') }}
