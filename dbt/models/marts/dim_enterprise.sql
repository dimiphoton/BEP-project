-- La famille est celle du code NACE, pas un attribut lu dans le fichier source.
select
    enterprise.enterprise_number,
    enterprise.enterprise_name,
    enterprise.nace_code,
    activity.activity_family,
    activity.method as classification_method,
    activity.confidence as classification_confidence
from {{ ref('stg_enterprise') }} as enterprise
left join {{ ref('stg_nace_activity') }} as activity
    on enterprise.nace_code = activity.nace_code
