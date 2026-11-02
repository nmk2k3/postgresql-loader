"""Create the products table using the database settings in .env."""

import sys

import psycopg

from postgresql_loader.database import PROJECT_ROOT, get_connection


def main() -> int:
    try:
        schema = (PROJECT_ROOT / "sql" / "products.sql").read_text(encoding="utf-8")
        with get_connection() as connection:
            # The connection context commits on success and rolls back on error.
            connection.execute(schema)
    except (OSError, ValueError, psycopg.Error) as error:
        print(f"Failed to create products table: {error}", file=sys.stderr)
        return 1

    print("Products table is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
