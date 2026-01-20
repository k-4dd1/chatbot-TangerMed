#!/bin/bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Wait for Postgres ---------------------------------------------------------
# ---------------------------------------------------------------------------

if [[ -n "${DATABASE_URI:-}" ]]; then
  echo "Waiting for database..."
  until python - <<END
import sys, time, sqlalchemy as sa, os
url = os.environ.get("DATABASE_URI")
engine = sa.create_engine(url, pool_pre_ping=True)
try:
    with engine.connect() as conn:
        conn.execute(sa.text("SELECT 1"))
except Exception as e:
    sys.exit(1)
END
  do
    echo "  database not ready, sleeping..."
    sleep 2
  done
fi

# ---------------------------------------------------------------------------
# Run Alembic migrations ----------------------------------------------------
# ---------------------------------------------------------------------------

echo "Running Alembic migrations..."
alembic upgrade head

# ---------------------------------------------------------------------------
# Start Uvicorn -------------------------------------------------------------
# ---------------------------------------------------------------------------

exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-4}