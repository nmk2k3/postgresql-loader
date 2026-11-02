"""Load products from a JSON file or a directory of JSON files."""

import argparse
import json
import sys
from pathlib import Path

import psycopg

from postgresql_loader.database import PROJECT_ROOT, get_connection


def load_products(path: Path) -> int:
    products = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(products, list):
        raise TypeError("Expected a JSON array of products.")

    rows = []
    for index, product in enumerate(products, start=1):
        if not isinstance(product, dict):
            raise TypeError(f"Product {index} must be a JSON object.")
        for field in ("id", "name", "url_key", "price"):
            if field not in product or product[field] is None:
                raise ValueError(
                    f"Product {index} is missing required field '{field}'."
                )

        images = product.get("images_url", [])
        if not isinstance(images, list) or any(
            not isinstance(url, str) for url in images
        ):
            raise ValueError(
                f"Product {index}: images_url must be an array of strings."
            )

        rows.append(
            (
                product["id"],
                product["name"],
                product["url_key"],
                product["price"],
                product.get("description"),
                images,
            )
        )

    if not rows:
        return 0

    statement = (PROJECT_ROOT / "sql" / "upsert_product.sql").read_text(
        encoding="utf-8"
    )
    # Commit each file together; a database error rolls back that file.
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.executemany(statement, rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        type=Path,
        nargs="?",
        default=PROJECT_ROOT / "data" / "sample.json",
        help="JSON file or directory to load (default: data/sample.json in the project)",
    )
    args = parser.parse_args()

    path = args.path
    try:
        if path.is_dir():
            files = sorted(file for file in path.glob("*.json") if file.is_file())
            if not files:
                raise ValueError("No JSON files found in the directory.")
        else:
            files = [path]

        for path in files:
            count = load_products(path)
            print(f"Loaded {count} products from {path}.")
    except FileNotFoundError as error:
        message = f"File not found: {error.filename or path}"
    except PermissionError as error:
        message = f"Permission denied reading: {error.filename or path}"
    except json.JSONDecodeError as error:
        message = (
            f"Invalid JSON at line {error.lineno}, column {error.colno}: {error.msg}"
        )
    except UnicodeError as error:
        message = f"Unable to decode file as UTF-8: {error}"
    except OSError as error:
        message = f"Unable to read input or SQL file: {error}"
    except psycopg.OperationalError as error:
        message = f"PostgreSQL connection or operation failed: {error}"
    except psycopg.IntegrityError as error:
        message = f"Product data violates a database constraint: {error}"
    except psycopg.Error as error:
        message = f"Database error: {error}"
    except (TypeError, ValueError) as error:
        message = str(error)
    else:
        return 0

    print(f"Failed to load products from {path}: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
