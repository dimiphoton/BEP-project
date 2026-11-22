#!/bin/bash
# Schémas raw/staging/marts/ops et rôles ingest_rw, dbt_rw, reader_ro.
# Lancé une seule fois, à la création du volume Postgres.
set -euo pipefail

: "${POSTGRES_USER:?POSTGRES_USER manquant}"
: "${POSTGRES_DB:?POSTGRES_DB manquant}"
: "${INGEST_PASSWORD:?INGEST_PASSWORD manquant}"
: "${DBT_PASSWORD:?DBT_PASSWORD manquant}"
: "${READER_PASSWORD:?READER_PASSWORD manquant}"

sql_quote() {
  local raw="$1"
  printf '%s' "${raw//\'/\'\'}"
}

psql_cmd() {
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" "$@"
}

role_exists() {
  psql_cmd -tAc "SELECT 1 FROM pg_roles WHERE rolname = '$1'"
}

ensure_role() {
  local role="$1"
  local password="$2"
  if [ "$(role_exists "$role")" = "1" ]; then
    psql_cmd -c "ALTER ROLE ${role} WITH LOGIN PASSWORD '${password}' NOSUPERUSER NOCREATEDB NOCREATEROLE"
  else
    psql_cmd -c "CREATE ROLE ${role} LOGIN PASSWORD '${password}' NOSUPERUSER NOCREATEDB NOCREATEROLE"
  fi
}

ensure_role ingest_rw "$(sql_quote "$INGEST_PASSWORD")"
ensure_role dbt_rw "$(sql_quote "$DBT_PASSWORD")"
ensure_role reader_ro "$(sql_quote "$READER_PASSWORD")"

psql_cmd <<EOSQL
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS marts;
CREATE SCHEMA IF NOT EXISTS ops;

-- dbt peut créer un schéma : droit sur la base, pas celui de créer une autre base.
DO \$\$
BEGIN
  EXECUTE format(
    'GRANT CONNECT ON DATABASE %I TO ingest_rw, dbt_rw, reader_ro',
    current_database()
  );
  EXECUTE format('GRANT CREATE ON DATABASE %I TO dbt_rw', current_database());
END
\$\$;

GRANT USAGE, CREATE ON SCHEMA raw, ops TO ingest_rw;
GRANT USAGE ON SCHEMA raw, ops TO dbt_rw;
GRANT USAGE, CREATE ON SCHEMA staging, marts TO dbt_rw;
GRANT USAGE ON SCHEMA marts TO reader_ro;

-- Tables futures : l'ingestion écrit raw/ops, dbt écrit les marts, la lecture les voit.
ALTER DEFAULT PRIVILEGES FOR ROLE ingest_rw IN SCHEMA raw
  GRANT SELECT ON TABLES TO dbt_rw;
ALTER DEFAULT PRIVILEGES FOR ROLE ingest_rw IN SCHEMA ops
  GRANT SELECT ON TABLES TO dbt_rw;
ALTER DEFAULT PRIVILEGES FOR ROLE dbt_rw IN SCHEMA marts
  GRANT SELECT ON TABLES TO reader_ro;
EOSQL
