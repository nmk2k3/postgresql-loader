"""Check the local PostgreSQL connection using settings from .env."""

import sys

import psycopg

from postgresql_loader.database import get_connection


def main() -> int:
    try:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user, version()")
            database, user, version = cursor.fetchone()
    except (OSError, ValueError, psycopg.Error) as error:
        print(f"PostgreSQL connection failed: {error}", file=sys.stderr)
        return 1

    print(f"Connected to database '{database}' as '{user}'.")
    print(version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
