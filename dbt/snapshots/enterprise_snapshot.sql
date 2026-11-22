-- Historise le nom et le code NACE. La stratégie check se passe d'un horodatage source.
{% snapshot enterprise_snapshot %}
{{
    config(
        target_schema='marts',
        unique_key='enterprise_number',
        strategy='check',
        check_cols=['enterprise_name', 'nace_code'],
    )
}}
select
    enterprise_number,
    enterprise_name,
    nace_code
from {{ ref('dim_enterprise') }}
{% endsnapshot %}
