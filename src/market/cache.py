"""
Quote Cache
5-minute TTL cache for market data backed by SQLite.
"""

from datetime import datetime, timedelta
from src.database.queries import upsert_market_quote, get_latest_quote


# In-memory cache
_cache = {}
_cache_ttl = timedelta(minutes=5)


def get_cached_quote(symbol):
    """Get a quote from cache if it's fresh enough."""
    # Check in-memory cache first
    if symbol in _cache:
        entry = _cache[symbol]
        if datetime.now() - entry['timestamp'] < _cache_ttl:
            return entry['data']

    # Check SQLite cache
    db_quote = get_latest_quote(symbol)
    if db_quote:
        try:
            quote_time = datetime.strptime(db_quote['quote_timestamp'], '%Y-%m-%d %H:%M:%S')
            if datetime.now() - quote_time < _cache_ttl:
                data = dict(db_quote)
                _cache[symbol] = {'data': data, 'timestamp': quote_time}
                return data
        except (ValueError, TypeError):
            pass

    return None


def set_cached_quote(symbol, quote_data):
    """Store a quote in both in-memory and SQLite cache."""
    now = datetime.now()

    # Update in-memory cache
    _cache[symbol] = {
        'data': quote_data,
        'timestamp': now,
    }

    # Update SQLite cache
    quote_data['symbol'] = symbol
    upsert_market_quote(quote_data)


def is_cache_fresh(symbol):
    """Check if cached quote is within TTL."""
    return get_cached_quote(symbol) is not None


def clear_cache():
    """Clear in-memory cache."""
    global _cache
    _cache = {}


def set_cache_ttl(seconds):
    """Update the cache TTL."""
    global _cache_ttl
    _cache_ttl = timedelta(seconds=seconds)
