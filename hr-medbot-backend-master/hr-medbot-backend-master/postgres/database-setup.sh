#! /bin/bash


function create_database() {
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
        DO \$\$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '$1') THEN
                RAISE NOTICE 'Creating database %', '$1';
                CREATE DATABASE $1 WITH OWNER = $POSTGRES_USER;
            END IF;
        END
        \$\$;
EOSQL
}

function create_extension() {
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
        DO \$\$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = '$1') THEN
                RAISE NOTICE 'Creating extension %', '$1';
                CREATE EXTENSION $1;
            END IF;
        END
        \$\$;
EOSQL
}

if [ -n "$TARGET_DATABASES" ]; then
    for db in $(echo $TARGET_DATABASES | tr "," "\n"); do
        create_database $db
    done
fi

if [ -n "$TARGET_EXTENSIONS" ]; then
    for ext in $(echo $TARGET_EXTENSIONS | tr "," "\n"); do
        create_extension $ext
    done
fi