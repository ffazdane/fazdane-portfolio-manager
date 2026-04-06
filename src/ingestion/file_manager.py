"""
File Manager
Handles file hashing, deduplication, and archival of imported files.
"""

import hashlib
import os
import shutil
from datetime import datetime
from src.database.connection import IMPORTS_DIR
from src.database.queries import check_file_hash_exists, insert_import_file


def compute_file_hash(file_bytes):
    """Compute SHA-256 hash of file contents."""
    return hashlib.sha256(file_bytes).hexdigest()


def is_duplicate_file(file_bytes):
    """Check if a file with the same hash has already been imported."""
    file_hash = compute_file_hash(file_bytes)
    return check_file_hash_exists(file_hash), file_hash


def archive_file(filename, file_bytes, broker):
    """
    Archive a raw import file to the imports directory.
    Returns the archive path.
    """
    os.makedirs(IMPORTS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_name = "".join(c for c in filename if c.isalnum() or c in '._-')
    archive_name = f"{broker}_{timestamp}_{safe_name}"
    archive_path = os.path.join(IMPORTS_DIR, archive_name)

    with open(archive_path, 'wb') as f:
        f.write(file_bytes)

    return archive_path


def register_import(filename, broker, file_hash, row_count, source_type='file'):
    """Register an import in the database. Returns import_id."""
    return insert_import_file(filename, broker, file_hash, row_count, source_type)
