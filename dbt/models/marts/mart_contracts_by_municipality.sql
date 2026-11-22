with contract_link as (
    select
        contract.notice_id,
        contract.nis_code,
        contract.amount_eur,
        link.enterprise_number,
        case when link.notice_id is not null then 1 else 0 end as is_linked
    from {{ ref('fact_public_contract') }} as contract
    left join {{ ref('stg_contract_enterprise') }} as link
        on link.notice_id = contract.notice_id
        and link.status = 'linked'
),

flagged as (
    select
        contract_link.notice_id,
        contract_link.nis_code,
        contract_link.amount_eur,
        contract_link.is_linked,
        case
            when exists (
                select 1
                from {{ ref('fact_establishment') }} as site
                where site.enterprise_number = contract_link.enterprise_number
                    and site.nis_code = contract_link.nis_code
            ) then 1
            else 0
        end as same_municipality
    from contract_link
)

select
    municipality.nis_code,
    municipality.municipality_name,
    count(*) as contract_count,
    sum(flagged.is_linked) as linked_count,
    sum(flagged.same_municipality) as same_municipality_count,
    sum(flagged.amount_eur) as amount_eur
from flagged
inner join {{ ref('dim_municipality') }} as municipality
    on municipality.nis_code = flagged.nis_code
group by municipality.nis_code, municipality.municipality_name
