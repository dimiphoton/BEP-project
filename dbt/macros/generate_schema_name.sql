-- Les schémas staging et marts existent déjà.
-- Le préfixe dbt par défaut (staging_marts) casserait les droits des rôles.
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
