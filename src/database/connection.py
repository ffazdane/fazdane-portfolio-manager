"""
SQLite Connection Manager
Provides thread-safe database connections with WAL mode for concurrent reads.
"""

import sqlite3
import os
from contextlib import contextmanager

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")
DB_PATH = os.path.join(DB_DIR, "portfolio.db")
IMPORTS_DIR = os.path.join(DB_DIR, "imports")


def get_db_path():
    """Get the database file path, creating directories if needed."""
    os.makedirs(DB_DIR, exist_ok=True)
    os.makedirs(IMPORTS_DIR, exist_ok=True)
    return DB_PATH


def get_connection(db_path=None):
    """
    Create a new SQLite connection with optimal settings.
    Each call returns a fresh connection (safe for Streamlit's threading model).
    """
    if db_path is None:
        db_path = get_db_path()

    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db():
    """
    Context manager for database transactions.
    Automatically commits on success, rolls back on failure.
    
    Usage:
        with get_db() as conn:
            conn.execute("INSERT INTO ...", (...))
    """
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_db_readonly():
    """
    Context manager for read-only database access.
    Does not commit or rollback.
    """
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
