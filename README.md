# PostgreSQL Loader

Load Tiki product JSON into PostgreSQL. PostgreSQL runs in Docker; Python runs
locally on Ubuntu/WSL.

## Setup

Requires Python 3.12+, uv, and Docker Compose. On WSL, enable your distribution
in Docker Desktop under **Settings > Resources > WSL Integration**.

Run commands from the project root:

```bash
uv sync
cp .env.example .env
chmod 600 .env
```

Set `POSTGRES_PASSWORD` in `.env`, then start PostgreSQL and create the table:

```bash
docker compose up -d --wait
uv run python -m postgresql_loader.create_tables
```

Python connects using `.env`: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`,
`DB_HOST` (default `127.0.0.1`), and `DB_PORT` (defaults to `POSTGRES_PORT`).
If you change the Docker port, keep `DB_PORT` and `POSTGRES_PORT` aligned.
Keep `.env` private; it is ignored by Git.

## Load products

Use a JSON array matching [data/sample.json](data/sample.json).

```bash
# Load the sample file
uv run python -m postgresql_loader.load_products

# Load one file
uv run python -m postgresql_loader.load_products data/sample.json

# Load all .json files directly inside a directory, in filename order
uv run python -m postgresql_loader.load_products data
```

Existing product IDs are updated. Each file uses one transaction. Loading stops
on failure, keeping previously completed files committed. Source files stay unchanged.

## Check the database

Test the Python connection:

```bash
uv run python tests/test_connection.py
```

Open PostgreSQL inside Docker:

```bash
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

```sql
\dt
\d products
SELECT COUNT(*) FROM products;
SELECT * FROM products LIMIT 10;
\q
```

## Run loader tests

```bash
uv run python -m unittest discover -s tests -p 'test_load_products.py' -v
```

Tests mock the database and do not require PostgreSQL.

Check code with Ruff:

```bash
uv run ruff check .
```

## Manage PostgreSQL

```bash
docker compose logs -f postgres
docker compose stop
docker compose start --wait
docker compose down
```

Data persists in a Docker volume. `docker compose down --volumes` deletes it.
Database credentials in `.env` initialize a new volume only; editing them does
not update an existing database.
