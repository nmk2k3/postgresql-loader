"""Shared PostgreSQL connection settings for local development."""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_connection() -> psycopg.Connection:
    load_dotenv(PROJECT_ROOT / ".env")

    if not os.getenv("POSTGRES_PASSWORD"):
        raise ValueError("Set POSTGRES_PASSWORD in .env before running this script.")

    port = os.getenv("DB_PORT", os.getenv("POSTGRES_PORT", "5432"))
    try:
        port_number = int(port)
    except ValueError:
        raise ValueError(
            "DB_PORT or POSTGRES_PORT must be an integer from 1 to 65535."
        ) from None
    if not 1 <= port_number <= 65535:
        raise ValueError("DB_PORT or POSTGRES_PORT must be an integer from 1 to 65535.")

    return psycopg.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=port_number,
        dbname=os.getenv("POSTGRES_DB", "tiki"),
        user=os.getenv("POSTGRES_USER", "tiki_loader"),
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=5,
    )
