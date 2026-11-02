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

    return psycopg.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "tiki"),
        user=os.getenv("POSTGRES_USER", "tiki_loader"),
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=5,
    )
