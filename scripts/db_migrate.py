"""
db_migrate.py — Safe schema migration tool for the Portfolio Manager.

This is the CORRECT way to deploy schema (datastructure) changes to production.

======================================================================
WORKFLOW — How to change the database schema without losing data
======================================================================

  1.  Edit src/database/schema.py:
        a. Increment SCHEMA_VERSION  (e.g. 1 → 2)
        b. Add a _migration_v2() function with ALTER TABLE statements

  2.  Test locally:
        python scripts/db_migrate.py status        # confirm current version
        python scripts/db_migrate.py migrate        # applies migration locally

  3.  Backup + push to persistent store:
        python scripts/db_migrate.py backup         # backup BEFORE code push
        git add src/database/schema.py
        git commit -m "schema: add tags column to trades (v2)"
        git push

  4.  Streamlit Cloud restarts, restores DB from persistent store (already
      migrated), and is ready with all old data intact.

======================================================================
Usage
======================================================================

  python scripts/db_migrate.py status     Show DB path, size, schema version
  python scripts/db_migrate.py backup     Backup current DB to persistent store
  python scripts/db_migrate.py migrate    Apply pending migrations, then backup
  python scripts/db_migrate.py restore    Restore DB from persistent store
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def cmd_status():
    """Display current database status and schema version."""
    from src.database.persistence import DB_PATH, _get_backend
    from src.database.schema import get_schema_version, SCHEMA_VERSION

    print("\nPortfolio Database Status")
    print("=" * 50)
    print(f"Path:            {DB_PATH}")

    if os.path.exists(DB_PATH):
        size_kb = os.path.getsize(DB_PATH) / 1024
        print(f"Size:            {size_kb:.1f} KB")
        current = get_schema_version()
        print(f"Schema version:  v{current}  (target: v{SCHEMA_VERSION})")
        if current < SCHEMA_VERSION:
            print(f"[!] {SCHEMA_VERSION - current} pending migration(s)")
        else:
            print("[OK] Schema is up to date")
    else:
        print("Status:          [!!] No database file found")

    print(f"Backend:         {_get_backend()}")
    print()



def cmd_backup(reason="manual"):
    """Backup the database to the persistent store."""
    from src.database.persistence import backup_database, DB_PATH

    print("\nBacking up database...")
    print("=" * 50)

    if not os.path.exists(DB_PATH):
        print("[ERROR] No database file found. Nothing to backup.")
        sys.exit(1)

    success, message = backup_database(reason=reason)
    if success:
        print(f"[OK] {message}")
    else:
        print(f"[ERROR] {message}")
        sys.exit(1)



def cmd_migrate():
    """Apply pending schema migrations, then backup the result."""
    from src.database.schema import (
        init_database, migrate_database,
        get_schema_version, SCHEMA_VERSION
    )
    from src.database.persistence import backup_database, DB_PATH

    print("\nSchema Migration")
    print("=" * 50)

    current = get_schema_version()
    print(f"Current version: v{current}")
    print(f"Target version:  v{SCHEMA_VERSION}")

    if current >= SCHEMA_VERSION:
        print("[OK] Already at target version. Nothing to do.")
        return

    # Pre-migration backup
    print("\nCreating pre-migration backup...")
    ok, msg = backup_database(reason="pre-migration")
    if ok:
        print(f"[OK] {msg}")
    else:
        print(f"[WARN] Backup failed: {msg}")
        answer = input("Continue migration anyway? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            sys.exit(0)

    # Apply migrations
    print(f"\nApplying migrations v{current} -> v{SCHEMA_VERSION}...")
    init_database()         # Ensure schema exists (CREATE IF NOT EXISTS)
    new_version = migrate_database()
    print(f"[OK] Migrations complete. Schema is now v{new_version}")

    # Post-migration backup (upload migrated DB)
    print("\nUploading migrated database...")
    ok, msg = backup_database(reason="post-migration")
    if ok:
        print(f"[OK] {msg}")
        print(f"\nReady to deploy:")
        print(f"  git add src/database/schema.py")
        print(f"  git commit -m 'schema: migration v{new_version}'")
        print(f"  git push")
        print(f"\n  Streamlit Cloud will restart, restore this migrated DB,")
        print(f"  and apply no migrations (already at v{new_version}).")
    else:
        print(f"[ERROR] Post-migration upload failed: {msg}")
        print("  Migrations were applied locally, but not pushed to persistent store.")
        sys.exit(1)



def cmd_restore():
    """Restore the database from the persistent store."""
    from src.database.persistence import restore_database, DB_PATH

    print("\nRestoring database from persistent store...")
    print("=" * 50)

    if os.path.exists(DB_PATH):
        answer = input(
            f"[!] A database already exists at {DB_PATH}.\n"
            "    Overwrite? [y/N] "
        ).strip().lower()
        if answer != "y":
            print("Aborted.")
            sys.exit(0)

    success, message = restore_database()
    if success:
        print(f"[OK] {message}")
        size_kb = os.path.getsize(DB_PATH) / 1024
        print(f"    Size: {size_kb:.1f} KB")
    else:
        print(f"[ERROR] {message}")
        sys.exit(1)



def main():
    parser = argparse.ArgumentParser(
        description="Portfolio DB migration and backup tool.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status",  help="Show DB path, size, and schema version")
    subparsers.add_parser("backup",  help="Backup current DB to persistent store")
    subparsers.add_parser("migrate", help="Apply pending schema migrations, then backup")
    subparsers.add_parser("restore", help="Restore DB from persistent store")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status()
    elif args.command == "backup":
        cmd_backup()
    elif args.command == "migrate":
        cmd_migrate()
    elif args.command == "restore":
        cmd_restore()


if __name__ == "__main__":
    main()
