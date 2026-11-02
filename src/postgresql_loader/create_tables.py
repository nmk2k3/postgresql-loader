"""Create the products table using the database settings in .env."""

import sys

import psycopg

from postgresql_loader.database import PROJECT_ROOT, get_connection


def main() -> int:
    schema_path = PROJECT_ROOT / "sql" / "products.sql"
    try:
        schema = schema_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        message = f"SQL file not found: {schema_path}"
    except PermissionError:
        message = f"Permission denied reading SQL file: {schema_path}"
    except (OSError, UnicodeError) as error:
        message = f"Unable to read SQL file {schema_path}: {error}"
    else:
        try:
            with get_connection() as connection:
                # The connection context commits on success and rolls back on error.
                connection.execute(schema)
        except psycopg.OperationalError as error:
            message = f"PostgreSQL connection or operation failed: {error}"
        except psycopg.Error as error:
            message = f"Failed to execute SQL from {schema_path}: {error}"
        except (OSError, ValueError) as error:
            message = f"Unable to load database configuration: {error}"
        else:
            print("Products table is ready.")
            return 0

    print(f"Failed to create products table: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
