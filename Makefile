# Convenience targets. On Windows without `make`, run the commands directly.

.PHONY: check install init

install:
	pip install -r requirements.txt

# Enable PostGIS (needs a reachable DB + .env). Uses libpq PG* env vars via psql.
init:
	psql -f sql/00_init.sql

# Step 1 acceptance: connect and print the PostGIS version.
check:
	python -m src.db
