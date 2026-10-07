#!/bin/sh
set -eu
PORT="${DB_PORT:-5432}"
echo "Waiting for PostgreSQL at ${POSTGRES_SEEDS}:${PORT}..."
until nc -z -w 5 "${POSTGRES_SEEDS}" "${PORT}"; do sleep 2; done

for DB_NAME in temporal temporal_visibility; do
  if [ "$DB_NAME" = "temporal" ]; then
    SCHEMA_DIR=/etc/temporal/schema/postgresql/v12/temporal/versioned
  else
    SCHEMA_DIR=/etc/temporal/schema/postgresql/v12/visibility/versioned
  fi
  TOOL="temporal-sql-tool --plugin postgres12 --ep ${POSTGRES_SEEDS} -u ${POSTGRES_USER} -p ${PORT} --db ${DB_NAME}"
  $TOOL create 2>/dev/null || echo "[$DB_NAME] already exists"
  $TOOL setup-schema -v 0.0 2>/dev/null || echo "[$DB_NAME] base schema already present"
  $TOOL update-schema -d "$SCHEMA_DIR"
done
echo "Temporal schema setup complete"
