"""Loader tests using temporary JSON files and a mocked database."""

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import psycopg

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
        with patch("sys.argv", ["load_products", str(self.path)]), redirect_stderr(output):
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
        self.connect.assert_not_called()

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


if __name__ == "__main__":
    unittest.main()
