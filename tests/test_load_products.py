"""Loader tests using temporary JSON files and a mocked database."""

import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import psycopg

from postgresql_loader import create_tables, database
from postgresql_loader import load_products as loader


class LoadProductsTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "products.json"
        self.product = {
            "id": 123456,
            "name": "iPhone's màn hình",
            "url_key": "iphone-15-128gb",
            "price": 16990000,
            "description": "Màn hình Super Retina XDR.",
            "images_url": [
                "https://example.com/front.jpg",
                "https://example.com/back.jpg",
            ],
        }
        patcher = patch.object(loader, "get_connection")
        self.connect = patcher.start()
        self.addCleanup(patcher.stop)
        self.connection = self.connect.return_value.__enter__.return_value
        self.cursor = self.connection.cursor.return_value.__enter__.return_value

    def write_json(self, value):
        self.path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def test_loads_products_with_unicode_and_ordered_images(self):
        second = dict(self.product, id=789012, name="Samsung Galaxy S24")
        self.write_json([self.product, second])
        original = self.path.read_bytes()

        self.assertEqual(loader.load_products(self.path), 2)

        statement, rows = self.cursor.executemany.call_args.args
        self.assertEqual(
            statement,
            (loader.PROJECT_ROOT / "sql" / "upsert_product.sql").read_text(
                encoding="utf-8"
            ),
        )
        self.assertEqual(
            rows,
            [
                (
                    product["id"],
                    product["name"],
                    product["url_key"],
                    product["price"],
                    product["description"],
                    product["images_url"],
                )
                for product in (self.product, second)
            ],
        )
        self.assertNotIn(self.product["name"], statement)
        self.assertIn("ON CONFLICT (id) DO UPDATE", statement)
        self.connect.return_value.__exit__.assert_called_once_with(None, None, None)
        self.assertEqual(self.path.read_bytes(), original)

    def test_defaults_optional_fields(self):
        product = {key: self.product[key] for key in ("id", "name", "url_key", "price")}
        self.write_json([product])
        self.assertEqual(loader.load_products(self.path), 1)
        rows = self.cursor.executemany.call_args.args[1]
        self.assertEqual(rows[0][-2:], (None, []))

    def test_empty_array_skips_database(self):
        self.write_json([])
        self.assertEqual(loader.load_products(self.path), 0)
        self.connect.assert_not_called()

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            loader.load_products(self.path)
        self.connect.assert_not_called()

    def test_invalid_json(self):
        self.path.write_text("{invalid", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            loader.load_products(self.path)
        self.connect.assert_not_called()

    def test_invalid_product_structure(self):
        for value in ({}, None, "products", [1], [None]):
            with self.subTest(value=value):
                self.write_json(value)
                with self.assertRaises(TypeError):
                    loader.load_products(self.path)
        self.connect.assert_not_called()

    def test_cli_reports_invalid_product_type(self):
        self.write_json([1])
        output = io.StringIO()
        with (
            patch("sys.argv", ["load_products", str(self.path)]),
            redirect_stderr(output),
        ):
            self.assertEqual(loader.main(), 1)
        self.assertIn("Product 1 must be a JSON object", output.getvalue())
        self.connect.assert_not_called()

    def test_missing_or_null_required_fields_prevent_partial_import(self):
        for field in ("id", "name", "url_key", "price"):
            for null in (False, True):
                with self.subTest(field=field, null=null):
                    invalid = dict(self.product)
                    if null:
                        invalid[field] = None
                    else:
                        del invalid[field]
                    self.write_json([self.product, invalid])
                    with self.assertRaisesRegex(ValueError, f"Product 2.*'{field}'"):
                        loader.load_products(self.path)
        self.connect.assert_not_called()

    def test_invalid_images(self):
        for images in (None, "https://example.com/image.jpg", [123], [None]):
            with self.subTest(images=images):
                self.write_json([dict(self.product, images_url=images)])
                with self.assertRaisesRegex(ValueError, "images_url"):
                    loader.load_products(self.path)
        self.connect.assert_not_called()

    def test_database_error_reaches_transaction_context(self):
        self.write_json([self.product])
        error = psycopg.errors.CheckViolation("invalid price")
        self.cursor.executemany.side_effect = error
        with self.assertRaises(psycopg.errors.CheckViolation):
            loader.load_products(self.path)
        # Psycopg receives the error on context exit so it can roll back.
        exception_type, exception, _ = self.connect.return_value.__exit__.call_args.args
        self.assertIs(exception_type, psycopg.errors.CheckViolation)
        self.assertIs(exception, error)

    def test_cli_reports_success(self):
        self.write_json([self.product])
        output = io.StringIO()
        with (
            patch("sys.argv", ["load_products", str(self.path)]),
            redirect_stdout(output),
        ):
            self.assertEqual(loader.main(), 0)
        self.assertIn("Loaded 1 products", output.getvalue())

    def test_cli_reports_file_error(self):
        output = io.StringIO()
        with (
            patch("sys.argv", ["load_products", str(self.path)]),
            redirect_stderr(output),
        ):
            self.assertEqual(loader.main(), 1)
        self.assertIn("Failed to load products", output.getvalue())
        self.assertIn("File not found", output.getvalue())
        self.connect.assert_not_called()

    def test_cli_reports_read_errors(self):
        for error, message in (
            (PermissionError("access denied"), "Permission denied reading"),
            (OSError("read failed"), "Unable to read input or SQL file"),
            (UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid byte"), "UTF-8"),
        ):
            with self.subTest(error=error):
                output = io.StringIO()
                with (
                    patch("sys.argv", ["load_products", str(self.path)]),
                    patch.object(Path, "read_text", side_effect=error),
                    redirect_stderr(output),
                ):
                    self.assertEqual(loader.main(), 1)
                self.assertIn(message, output.getvalue())
                self.assertIn(str(self.path), output.getvalue())
        self.connect.assert_not_called()

    def test_cli_reports_json_location(self):
        self.path.write_text("[\n  {invalid}\n]", encoding="utf-8")
        output = io.StringIO()
        with (
            patch("sys.argv", ["load_products", str(self.path)]),
            redirect_stderr(output),
        ):
            self.assertEqual(loader.main(), 1)
        self.assertIn("Invalid JSON at line 2, column 4", output.getvalue())
        self.connect.assert_not_called()

    def test_cli_reports_connection_error(self):
        self.write_json([self.product])
        self.connect.side_effect = psycopg.OperationalError("connection refused")
        output = io.StringIO()
        with (
            patch("sys.argv", ["load_products", str(self.path)]),
            redirect_stderr(output),
        ):
            self.assertEqual(loader.main(), 1)
        self.assertIn("PostgreSQL connection or operation failed", output.getvalue())
        self.assertIn("connection refused", output.getvalue())

    def test_cli_reports_database_errors_and_preserves_rollback(self):
        self.write_json([self.product])
        for error, message in (
            (psycopg.errors.CheckViolation("invalid price"), "database constraint"),
            (
                psycopg.OperationalError("connection lost"),
                "connection or operation failed",
            ),
            (psycopg.ProgrammingError("bad SQL"), "Database error"),
        ):
            with self.subTest(error=error):
                self.cursor.executemany.side_effect = error
                output = io.StringIO()
                with (
                    patch("sys.argv", ["load_products", str(self.path)]),
                    redirect_stderr(output),
                ):
                    self.assertEqual(loader.main(), 1)
                self.assertIn(message, output.getvalue())
                self.assertIs(
                    self.connect.return_value.__exit__.call_args.args[1], error
                )

    def test_directory_loads_matching_files_in_order_with_separate_transactions(self):
        directory = self.path.parent
        # Create files out of order, with a repeated ID whose later name wins.
        for filename, name in (("sample.json", "Later"), ("catalog.json", "Earlier")):
            (directory / filename).write_text(
                json.dumps([dict(self.product, name=name)]),
                encoding="utf-8",
            )
        (directory / "notes.txt").write_text("invalid", encoding="utf-8")
        (directory / "products_003.json").mkdir()
        nested = directory / "nested"
        nested.mkdir()
        (nested / "products_004.json").write_text("invalid", encoding="utf-8")

        output = io.StringIO()
        with (
            patch("sys.argv", ["load_products", str(directory)]),
            redirect_stdout(output),
        ):
            self.assertEqual(loader.main(), 0)

        self.assertEqual(self.connect.call_count, 2)
        names = [call.args[1][0][1] for call in self.cursor.executemany.call_args_list]
        self.assertEqual(names, ["Earlier", "Later"])
        self.assertEqual(self.connect.return_value.__exit__.call_count, 2)
        for call in self.connect.return_value.__exit__.call_args_list:
            self.assertEqual(call.args, (None, None, None))
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("catalog.json", lines[0])
        self.assertIn("sample.json", lines[1])

    def test_directory_without_matches_reports_error(self):
        (self.path.parent / "notes.txt").write_text("not JSON", encoding="utf-8")
        output = io.StringIO()
        with (
            patch("sys.argv", ["load_products", str(self.path.parent)]),
            redirect_stderr(output),
        ):
            self.assertEqual(loader.main(), 1)
        self.assertIn("No JSON files", output.getvalue())
        self.connect.assert_not_called()

    def test_directory_stops_on_invalid_file_after_committing_previous_file(self):
        directory = self.path.parent
        for number in (1, 2, 3):
            (directory / f"products_{number:03}.json").write_text(
                json.dumps([self.product]),
                encoding="utf-8",
            )
        (directory / "products_002.json").write_text("invalid", encoding="utf-8")
        output, errors = io.StringIO(), io.StringIO()
        with (
            patch("sys.argv", ["load_products", str(directory)]),
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            self.assertEqual(loader.main(), 1)
        self.connect.assert_called_once()
        self.connect.return_value.__exit__.assert_called_once_with(None, None, None)
        self.assertIn("products_001.json", output.getvalue())
        self.assertIn("products_002.json", errors.getvalue())
        self.assertNotIn("products_003.json", output.getvalue())

    def test_directory_stops_on_database_failure(self):
        directory = self.path.parent
        for number in (1, 2, 3):
            (directory / f"products_{number:03}.json").write_text(
                json.dumps([self.product]),
                encoding="utf-8",
            )
        error = psycopg.errors.CheckViolation("invalid price")
        self.cursor.executemany.side_effect = [None, error]
        output, errors = io.StringIO(), io.StringIO()
        with (
            patch("sys.argv", ["load_products", str(directory)]),
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            self.assertEqual(loader.main(), 1)
        self.assertEqual(self.connect.call_count, 2)
        exits = self.connect.return_value.__exit__.call_args_list
        self.assertEqual(exits[0].args, (None, None, None))
        self.assertIs(exits[1].args[1], error)
        self.assertIn("products_002.json", errors.getvalue())
        self.assertNotIn("products_003.json", output.getvalue())


class CreateTablesTests(unittest.TestCase):
    def test_sql_read_errors_skip_database(self):
        for error, message in (
            (FileNotFoundError(), "SQL file not found"),
            (PermissionError(), "Permission denied reading SQL file"),
            (OSError("read failed"), "Unable to read SQL file"),
            (
                UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid byte"),
                "Unable to read SQL file",
            ),
        ):
            with self.subTest(error=error):
                output = io.StringIO()
                with (
                    patch.object(Path, "read_text", side_effect=error),
                    patch.object(create_tables, "get_connection") as connect,
                    redirect_stderr(output),
                ):
                    self.assertEqual(create_tables.main(), 1)
                self.assertIn(message, output.getvalue())
                self.assertIn("products.sql", output.getvalue())
                connect.assert_not_called()

    def test_connection_and_configuration_errors(self):
        for error, message in (
            (
                psycopg.OperationalError("connection refused"),
                "connection or operation failed",
            ),
            (ValueError("missing password"), "database configuration"),
            (OSError("cannot read .env"), "database configuration"),
        ):
            with self.subTest(error=error):
                output = io.StringIO()
                with (
                    patch.object(create_tables, "get_connection", side_effect=error),
                    redirect_stderr(output),
                ):
                    self.assertEqual(create_tables.main(), 1)
                self.assertIn(message, output.getvalue())

    def test_sql_error_reaches_transaction_context(self):
        error = psycopg.ProgrammingError("bad SQL")
        output = io.StringIO()
        with (
            patch.object(create_tables, "get_connection") as connect,
            redirect_stderr(output),
        ):
            connect.return_value.__enter__.return_value.execute.side_effect = error
            self.assertEqual(create_tables.main(), 1)
        self.assertIn("Failed to execute SQL", output.getvalue())
        self.assertIs(connect.return_value.__exit__.call_args.args[1], error)

    def test_success_commits_transaction(self):
        with (
            patch.object(create_tables, "get_connection") as connect,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(create_tables.main(), 0)
        connect.return_value.__exit__.assert_called_once_with(None, None, None)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        for patcher in (
            patch.dict(os.environ, {"POSTGRES_PASSWORD": "test-password"}, clear=True),
            patch.object(database, "load_dotenv"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_missing_password_skips_connection(self):
        del os.environ["POSTGRES_PASSWORD"]
        with (
            patch.object(database.psycopg, "connect") as connect,
            self.assertRaisesRegex(ValueError, "Set POSTGRES_PASSWORD"),
        ):
            database.get_connection()
        connect.assert_not_called()

    def test_invalid_port_skips_connection(self):
        for setting in ("DB_PORT", "POSTGRES_PORT"):
            for port in ("", "invalid", "0", "65536"):
                with self.subTest(setting=setting, port=port):
                    with (
                        patch.dict(os.environ, {setting: port}),
                        patch.object(database.psycopg, "connect") as connect,
                        self.assertRaisesRegex(ValueError, "integer from 1 to 65535"),
                    ):
                        database.get_connection()
                    connect.assert_not_called()

    def test_connection_failure_propagates_to_cli(self):
        error = psycopg.OperationalError("connection refused")
        with (
            patch.object(database.psycopg, "connect", side_effect=error),
            self.assertRaises(psycopg.OperationalError) as caught,
        ):
            database.get_connection()
        self.assertIs(caught.exception, error)

    def test_port_defaults_and_overrides(self):
        for settings, expected_port in (
            ({}, 5432),
            ({"POSTGRES_PORT": "5433"}, 5433),
            ({"POSTGRES_PORT": "5433", "DB_PORT": "5434"}, 5434),
        ):
            with self.subTest(settings=settings):
                with (
                    patch.dict(os.environ, settings),
                    patch.object(database.psycopg, "connect") as connect,
                ):
                    self.assertIs(database.get_connection(), connect.return_value)
                self.assertEqual(connect.call_args.kwargs["port"], expected_port)


if __name__ == "__main__":
    unittest.main()
