"""
Transaction Normalizer
Maps broker-specific parsed rows into the standardized normalized transaction schema.
"""

import hashlib
import json
from datetime import datetime


def normalize_transactions(raw_transactions, broker_name):
    """
    Convert a list of broker-specific parsed transaction dicts
    into normalized transaction dicts ready for database insertion.
    """
    normalized = []

    for raw in raw_transactions:
        try:
            norm = _normalize_single(raw, broker_name)
            if norm:
                normalized.append(norm)
        except Exception as e:
            print(f"Warning: Failed to normalize transaction: {e}")
            continue

    return normalized


def _normalize_single(raw, broker_name):
    """Normalize a single raw transaction dict."""
    # Parse and normalize the date
    trade_date = _normalize_date(raw.get('date', ''))
    if not trade_date:
        return None

    # Build the normalized record
    norm = {
        'broker': broker_name,
        'account': raw.get('account', 'default'),
        'trade_date': trade_date,
        'settlement_date': None,
        'symbol': raw.get('symbol', ''),
        'underlying': raw.get('underlying', raw.get('symbol', '')),
        'expiry': _normalize_date(raw.get('expiry')) if raw.get('expiry') else None,
        'strike': raw.get('strike'),
        'put_call': raw.get('put_call'),
        'side': raw.get('side', 'BUY'),
        'quantity': abs(float(raw.get('quantity', 0))),
        'price': float(raw.get('price', 0)),
        'fees': abs(float(raw.get('fees', 0))),
        'multiplier': 100,
        'txn_type': raw.get('normalized_type', 'TRADE'),
        'open_close_flag': raw.get('open_close'),
        'instrument_type': raw.get('instrument_type', 'EQUITY_OPTION'),
        'order_id': raw.get('order_id'),
        'description': raw.get('description', ''),
        'net_amount': raw.get('amount'),
    }

    # Compute dedup hash 
    dedup_string = (
        f"{norm['broker']}|{norm['account']}|{norm['trade_date']}|"
        f"{norm['symbol']}|{norm['side']}|{norm['quantity']}|"
        f"{norm['price']}|{norm['txn_type']}"
    )
    norm['dedup_hash'] = hashlib.sha256(dedup_string.encode()).hexdigest()

    return norm


def _normalize_date(date_str):
    """Normalize various date formats to YYYY-MM-DD."""
    if not date_str or date_str == 'None' or date_str == 'nan':
        return None

    date_str = str(date_str).strip()

    # Already in target format
    if len(date_str) >= 10 and date_str[4] == '-' and date_str[7] == '-':
        return date_str[:10]

    formats = [
        '%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d', '%m-%d-%Y',
        '%Y/%m/%d', '%d-%b-%Y', '%b %d, %Y', '%B %d, %Y',
        '%m/%d/%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S',
        '%m/%d/%Y %I:%M %p', '%m/%d/%y %H:%M:%S',
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str[:min(len(date_str), 19)], fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue

    return date_str[:10] if len(date_str) >= 10 else None
