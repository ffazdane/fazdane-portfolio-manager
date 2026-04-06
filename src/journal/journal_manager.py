"""
Trade Journal Manager
CRUD operations for trade journal entries.
Notes are attached to trade_id and preserved through all status transitions.
"""

from src.database.queries import (
    insert_journal_entry, get_journal_entries, get_journal_entry_count
)


# Valid note types
NOTE_TYPES = [
    ('entry_thesis', '📝 Entry Thesis'),
    ('adjustment_note', '🔧 Adjustment Note'),
    ('warning_note', '⚠️ Warning Note'),
    ('exit_reason', '🚪 Exit Reason'),
    ('lesson_learned', '🎓 Lesson Learned'),
    ('emotional_note', '💭 Emotional Note'),
    ('market_context', '📊 Market Context'),
    ('post_trade_review', '🔍 Post-Trade Review'),
    ('general', '📌 General Note'),
]

NOTE_TYPE_MAP = {k: v for k, v in NOTE_TYPES}


def add_journal_entry(trade_id, note_text, note_type='general'):
    """
    Add a journal entry for a trade.
    The entry is attached to the trade_id and will persist
    through all lifecycle transitions.
    """
    if not note_text or not note_text.strip():
        return None

    if note_type not in NOTE_TYPE_MAP:
        note_type = 'general'

    return insert_journal_entry(trade_id, note_text.strip(), note_type)


def get_trade_journal(trade_id):
    """
    Get all journal entries for a trade, ordered chronologically.
    Returns list of journal entry dicts.
    """
    entries = get_journal_entries(trade_id)
    return [dict(e) for e in entries]


def get_note_count(trade_id):
    """Get the count of journal entries for a trade."""
    return get_journal_entry_count(trade_id)


def get_available_note_types():
    """Get list of available note type options."""
    return NOTE_TYPES
