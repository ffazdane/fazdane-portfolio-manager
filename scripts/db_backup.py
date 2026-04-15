"""
db_backup.py — Backup the portfolio database to the configured persistent store.

Usage:
    python scripts/db_backup.py
    python scripts/db_backup.py --reason "pre-release"

This creates a local timestamped backup in data/backups/ AND uploads to the
remote backend configured in .env or Streamlit secrets (GitHub Release / S3).

Run this anytime you want to checkpoint your data — especially before deploying
code changes that include schema migrations.
"""

import sys
import os
import argparse

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(
        description="Backup portfolio.db to the configured persistent store."
    )
    parser.add_argument(
        "--reason",
        default="manual",
        help="Label for this backup (e.g. 'pre-migration', 'daily'). Default: manual",
    )
    args = parser.parse_args()

    from src.database.persistence import backup_database, DB_PATH

    print("\nPortfolio Database Backup")
    print("=" * 50)
    print(f"Source:  {DB_PATH}")
    print(f"Reason:  {args.reason}")
    print()

    if not os.path.exists(DB_PATH):
        print("[ERROR] No database file found. Nothing to backup.")
        sys.exit(1)

    size_kb = os.path.getsize(DB_PATH) / 1024
    print(f"DB size: {size_kb:.1f} KB")

    success, message = backup_database(reason=args.reason)

    if success:
        print(f"[OK] {message}")
    else:
        print(f"[ERROR] {message}")
        sys.exit(1)


if __name__ == "__main__":
    main()
