"""
Database Query Functions
Reusable parameterized queries for all CRUD operations.
"""

import json
from src.database.connection import get_db, get_db_readonly


# ============================================================
# SETTINGS
# ============================================================

def get_setting(key, default=None):
    """Get a setting value by key."""
    with get_db_readonly() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key, value, description=None):
    """Set a setting value."""
    with get_db() as conn:
        if description:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value, description, updated_at) VALUES (?, ?, ?, datetime('now'))",
                (key, str(value), description)
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))",
                (key, str(value))
            )


def get_all_settings():
    """Get all settings as a dict."""
    with get_db_readonly() as conn:
        rows = conn.execute("SELECT key, value, description FROM settings").fetchall()
        return {r["key"]: {"value": r["value"], "description": r["description"]} for r in rows}


# ============================================================
# RAW IMPORT FILES
# ============================================================

def insert_import_file(filename, broker, file_hash, row_count, source_type='file'):
    """Insert a new import file record. Returns import_id."""
    with get_db() as conn:
        # Check if hash already exists to avoid UNIQUE constraint error on re-import
        cursor = conn.execute("SELECT import_id FROM raw_import_files WHERE file_hash = ?", (file_hash,))
        row = cursor.fetchone()
        
        if row:
            import_id = row["import_id"]
            conn.execute(
                "UPDATE raw_import_files SET processed_status = 'processing', row_count = ?, filename = ? WHERE import_id = ?",
                (row_count, filename, import_id)
            )
            return import_id
            
        cursor = conn.execute(
            """INSERT INTO raw_import_files (filename, broker, file_hash, row_count, source_type, processed_status)
               VALUES (?, ?, ?, ?, ?, 'processing')""",
            (filename, broker, file_hash, row_count, source_type)
        )
        return cursor.lastrowid


def update_import_status(import_id, status, notes=None):
    """Update the processing status of an import."""
    with get_db() as conn:
        conn.execute(
            "UPDATE raw_import_files SET processed_status = ?, notes = ? WHERE import_id = ?",
            (status, notes, import_id)
        )


def check_file_hash_exists(file_hash):
    """Check if a file with this hash has already been imported."""
    with get_db_readonly() as conn:
        row = conn.execute("SELECT import_id FROM raw_import_files WHERE file_hash = ?", (file_hash,)).fetchone()
        return row is not None


def get_import_history():
    """Get all import records ordered by most recent."""
    with get_db_readonly() as conn:
        return conn.execute(
            "SELECT * FROM raw_import_files ORDER BY upload_timestamp DESC"
        ).fetchall()


# ============================================================
# RAW TRANSACTIONS
# ============================================================

def insert_raw_transaction(import_id, raw_payload, broker, source_row_number):
    """Insert a raw transaction row. Returns raw_txn_id."""
    with get_db() as conn:
        payload_json = json.dumps(raw_payload) if isinstance(raw_payload, dict) else raw_payload
        cursor = conn.execute(
            """INSERT INTO raw_transactions (import_id, raw_payload, broker, source_row_number)
               VALUES (?, ?, ?, ?)""",
            (import_id, payload_json, broker, source_row_number)
        )
        return cursor.lastrowid


def insert_raw_transactions_bulk(import_id, rows, broker):
    """Insert multiple raw transaction rows."""
    with get_db() as conn:
        for i, row in enumerate(rows):
            payload_json = json.dumps(row) if isinstance(row, dict) else row
            conn.execute(
                """INSERT INTO raw_transactions (import_id, raw_payload, broker, source_row_number)
                   VALUES (?, ?, ?, ?)""",
                (import_id, payload_json, broker, i + 1)
            )


# ============================================================
# NORMALIZED TRANSACTIONS
# ============================================================

def insert_normalized_transaction(txn_data):
    """Insert a normalized transaction. Returns txn_id or None if duplicate."""
    with get_db() as conn:
        try:
            cursor = conn.execute(
                """INSERT INTO normalized_transactions
                   (raw_txn_id, broker, account, trade_date, settlement_date, symbol, underlying,
                    expiry, strike, put_call, side, quantity, price, fees, multiplier,
                    txn_type, open_close_flag, instrument_type, order_id, description, net_amount, dedup_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    txn_data.get('raw_txn_id'),
                    txn_data['broker'],
                    txn_data['account'],
                    txn_data['trade_date'],
                    txn_data.get('settlement_date'),
                    txn_data['symbol'],
                    txn_data['underlying'],
                    txn_data.get('expiry'),
                    txn_data.get('strike'),
                    txn_data.get('put_call'),
                    txn_data['side'],
                    txn_data['quantity'],
                    txn_data['price'],
                    txn_data.get('fees', 0),
                    txn_data.get('multiplier', 100),
                    txn_data['txn_type'],
                    txn_data.get('open_close_flag'),
                    txn_data.get('instrument_type', 'EQUITY_OPTION'),
                    txn_data.get('order_id'),
                    txn_data.get('description'),
                    txn_data.get('net_amount'),
                    txn_data.get('dedup_hash'),
                )
            )
            return cursor.lastrowid
        except Exception:
            # Duplicate hash - skip
            return None


def insert_normalized_transactions_bulk(txn_list):
    """Insert multiple normalized transactions. Returns count of new rows."""
    count = 0
    for txn in txn_list:
        result = insert_normalized_transaction(txn)
        if result:
            count += 1
    return count


def get_all_normalized_transactions(account=None, broker=None, underlying=None, limit=1000):
    """Get normalized transactions with optional filters."""
    with get_db_readonly() as conn:
        query = "SELECT * FROM normalized_transactions WHERE 1=1"
        params = []
        if account:
            query += " AND account = ?"
            params.append(account)
        if broker:
            query += " AND broker = ?"
            params.append(broker)
        if underlying:
            query += " AND underlying = ?"
            params.append(underlying)
        query += " ORDER BY trade_date DESC LIMIT ?"
        params.append(limit)
        return conn.execute(query, params).fetchall()


def get_option_transactions(account=None):
    """Get all option transactions for position building."""
    with get_db_readonly() as conn:
        query = """SELECT * FROM normalized_transactions 
                   WHERE instrument_type = 'EQUITY_OPTION'"""
        params = []
        if account:
            query += " AND account = ?"
            params.append(account)
        query += " ORDER BY trade_date ASC"
        return conn.execute(query, params).fetchall()


# ============================================================
# TRADES
# ============================================================

def insert_trade(trade_data):
    """Insert a new trade record. Returns trade_id."""
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO trades
               (parent_trade_id, roll_group_id, account, broker, underlying, strategy_type,
                open_date, close_date, status, entry_credit_debit, realized_pnl, unrealized_pnl,
                max_profit, max_loss, days_held, result_tag)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade_data.get('parent_trade_id'),
                trade_data.get('roll_group_id'),
                trade_data['account'],
                trade_data['broker'],
                trade_data['underlying'],
                trade_data['strategy_type'],
                trade_data['open_date'],
                trade_data.get('close_date'),
                trade_data.get('status', 'ACTIVE'),
                trade_data.get('entry_credit_debit', 0),
                trade_data.get('realized_pnl', 0),
                trade_data.get('unrealized_pnl', 0),
                trade_data.get('max_profit'),
                trade_data.get('max_loss'),
                trade_data.get('days_held', 0),
                trade_data.get('result_tag'),
            )
        )
        return cursor.lastrowid


def update_trade(trade_id, updates):
    """Update a trade record with a dict of field:value pairs."""
    if not updates:
        return
    updates['updated_at'] = "datetime('now')"
    set_clause = ", ".join(f"{k} = ?" for k in updates if k != 'updated_at')
    set_clause += ", updated_at = datetime('now')"
    values = [v for k, v in updates.items() if k != 'updated_at']
    values.append(trade_id)
    with get_db() as conn:
        conn.execute(f"UPDATE trades SET {set_clause} WHERE trade_id = ?", values)


def delete_trade(trade_id):
    """Delete a trade and all associated cascade records."""
    with get_db() as conn:
        conn.execute("DELETE FROM alerts WHERE trade_id = ?", (trade_id,))
        conn.execute("DELETE FROM trade_snapshots WHERE trade_id = ?", (trade_id,))
        conn.execute("DELETE FROM trade_journal WHERE trade_id = ?", (trade_id,))
        conn.execute("DELETE FROM trade_legs WHERE trade_id = ?", (trade_id,))
        conn.execute("DELETE FROM trades WHERE trade_id = ?", (trade_id,))


def get_active_trades(account=None, broker=None):
    """Get all trades with open-risk statuses."""
    with get_db_readonly() as conn:
        query = """SELECT t.*, 
                          COUNT(DISTINCT tl.leg_id) as leg_count,
                          COUNT(DISTINCT tj.journal_id) as note_count
                   FROM trades t
                   LEFT JOIN trade_legs tl ON t.trade_id = tl.trade_id
                   LEFT JOIN trade_journal tj ON t.trade_id = tj.trade_id
                   WHERE t.status IN ('ACTIVE', 'PARTIALLY_CLOSED', 'ADJUSTED', 'ROLLED_OPEN')"""
        params = []
        if account:
            query += " AND t.account = ?"
            params.append(account)
        if broker:
            query += " AND t.broker = ?"
            params.append(broker)
        query += " GROUP BY t.trade_id ORDER BY t.open_date DESC"
        return conn.execute(query, params).fetchall()


def get_historical_trades(account=None, broker=None, strategy=None, limit=500):
    """Get all trades with historical statuses."""
    with get_db_readonly() as conn:
        query = """SELECT t.*,
                          COUNT(DISTINCT tj.journal_id) as note_count
                   FROM trades t
                   LEFT JOIN trade_journal tj ON t.trade_id = tj.trade_id
                   WHERE t.status IN ('CLOSED_WIN', 'CLOSED_LOSS', 'EXPIRED_WORTHLESS', 
                                       'ASSIGNED_RESOLVED', 'EXERCISED_RESOLVED', 'ROLLED_HISTORICAL')"""
        params = []
        if account:
            query += " AND t.account = ?"
            params.append(account)
        if broker:
            query += " AND t.broker = ?"
            params.append(broker)
        if strategy:
            query += " AND t.strategy_type = ?"
            params.append(strategy)
        query += " GROUP BY t.trade_id ORDER BY t.close_date DESC LIMIT ?"
        params.append(limit)
        return conn.execute(query, params).fetchall()


def get_trade_by_id(trade_id):
    """Get a single trade with all details."""
    with get_db_readonly() as conn:
        return conn.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,)).fetchone()


def get_all_trades():
    """Get all trades regardless of status."""
    with get_db_readonly() as conn:
        return conn.execute("SELECT * FROM trades ORDER BY open_date DESC").fetchall()


def get_unique_accounts():
    """Get unique account numbers across all trades."""
    with get_db_readonly() as conn:
        rows = conn.execute("SELECT DISTINCT account FROM trades ORDER BY account").fetchall()
        return [r["account"] for r in rows]


def get_unique_brokers():
    """Get unique broker names across all trades."""
    with get_db_readonly() as conn:
        rows = conn.execute("SELECT DISTINCT broker FROM trades ORDER BY broker").fetchall()
        return [r["broker"] for r in rows]


# ============================================================
# TRADE LEGS
# ============================================================

def insert_trade_leg(leg_data):
    """Insert a trade leg. Returns leg_id."""
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO trade_legs
               (trade_id, symbol, underlying, expiry, strike, option_type, side,
                qty_open, qty_closed, entry_price, exit_price, current_mark, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                leg_data['trade_id'],
                leg_data['symbol'],
                leg_data['underlying'],
                leg_data.get('expiry'),
                leg_data.get('strike'),
                leg_data.get('option_type'),
                leg_data['side'],
                leg_data.get('qty_open', 0),
                leg_data.get('qty_closed', 0),
                leg_data.get('entry_price', 0),
                leg_data.get('exit_price'),
                leg_data.get('current_mark'),
                leg_data.get('status', 'OPEN'),
            )
        )
        return cursor.lastrowid


def get_trade_legs(trade_id):
    """Get all legs for a trade."""
    with get_db_readonly() as conn:
        return conn.execute(
            "SELECT * FROM trade_legs WHERE trade_id = ? ORDER BY strike, option_type",
            (trade_id,)
        ).fetchall()


def update_trade_leg(leg_id, updates):
    """Update a trade leg."""
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    set_clause += ", updated_at = datetime('now')"
    values = list(updates.values())
    values.append(leg_id)
    with get_db() as conn:
        conn.execute(f"UPDATE trade_legs SET {set_clause} WHERE leg_id = ?", values)


def delete_trade_leg(leg_id):
    """Delete a trade leg permanently from the database."""
    with get_db() as conn:
        conn.execute("DELETE FROM trade_legs WHERE leg_id = ?", (leg_id,))


# ============================================================
# TRADE JOURNAL
# ============================================================

def insert_journal_entry(trade_id, note_text, note_type='general'):
    """Insert a journal entry. Returns journal_id."""
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO trade_journal (trade_id, note_type, note_text)
               VALUES (?, ?, ?)""",
            (trade_id, note_type, note_text)
        )
        return cursor.lastrowid


def get_journal_entries(trade_id):
    """Get all journal entries for a trade, ordered chronologically."""
    with get_db_readonly() as conn:
        return conn.execute(
            "SELECT * FROM trade_journal WHERE trade_id = ? ORDER BY timestamp ASC",
            (trade_id,)
        ).fetchall()


def get_journal_entry_count(trade_id):
    """Get number of journal entries for a trade."""
    with get_db_readonly() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as count FROM trade_journal WHERE trade_id = ?",
            (trade_id,)
        ).fetchone()
        return row["count"]


# ============================================================
# MARKET QUOTES
# ============================================================

def delete_active_trades_by_underlying(underlyings):
    """Delete all active trades and their legs for specific underlyings to prevent duplicates on re-import."""
    if not underlyings:
        return
    with get_db() as conn:
        placeholders = ",".join(["?"] * len(underlyings))
        
        # Get active trade IDs for these underlyings
        cursor = conn.execute(
            f"SELECT trade_id FROM trades WHERE status IN ('ACTIVE', 'PARTIALLY_CLOSED', 'ADJUSTED', 'ROLLED_OPEN') AND underlying IN ({placeholders})",
            list(underlyings)
        )
        trade_ids = [row['trade_id'] for row in cursor.fetchall()]
        
        if not trade_ids:
            return
            
        trade_placeholders = ",".join(["?"] * len(trade_ids))
        
        # Delete legs first
        conn.execute(f"DELETE FROM trade_legs WHERE trade_id IN ({trade_placeholders})", trade_ids)
        
        # Delete trades
        conn.execute(f"DELETE FROM trades WHERE trade_id IN ({trade_placeholders})", trade_ids)


def delete_active_trades_by_account_and_underlying(account, underlyings):
    """Delete all active trades and their legs for a specific account and underlyings to prevent duplicates on API re-import."""
    if not underlyings or not account:
        return
    with get_db() as conn:
        placeholders = ",".join(["?"] * len(underlyings))
        params = [account] + list(underlyings)
        
        # Get active trade IDs for these underlyings and this specific account
        cursor = conn.execute(
            f"SELECT trade_id FROM trades WHERE status IN ('ACTIVE', 'PARTIALLY_CLOSED', 'ADJUSTED', 'ROLLED_OPEN') AND account = ? AND underlying IN ({placeholders})",
            params
        )
        trade_ids = [row['trade_id'] for row in cursor.fetchall()]
        
        if not trade_ids:
            return
            
        trade_placeholders = ",".join(["?"] * len(trade_ids))
        
        # Delete legs first
        conn.execute(f"DELETE FROM trade_legs WHERE trade_id IN ({trade_placeholders})", trade_ids)
        
        # Delete trades
        conn.execute(f"DELETE FROM trades WHERE trade_id IN ({trade_placeholders})", trade_ids)


def upsert_market_quote(quote_data):
    """Insert or update a market quote."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO market_quotes
               (symbol, quote_timestamp, underlying_price, option_mark, bid, ask, last,
                delta, gamma, theta, vega, iv, volume, open_interest)
               VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                quote_data['symbol'],
                quote_data.get('underlying_price'),
                quote_data.get('option_mark'),
                quote_data.get('bid'),
                quote_data.get('ask'),
                quote_data.get('last'),
                quote_data.get('delta'),
                quote_data.get('gamma'),
                quote_data.get('theta'),
                quote_data.get('vega'),
                quote_data.get('iv'),
                quote_data.get('volume'),
                quote_data.get('open_interest'),
            )
        )


def get_latest_quote(symbol):
    """Get the most recent quote for a symbol."""
    with get_db_readonly() as conn:
        return conn.execute(
            "SELECT * FROM market_quotes WHERE symbol = ? ORDER BY quote_timestamp DESC LIMIT 1",
            (symbol,)
        ).fetchone()


def get_latest_quotes_batch(symbols):
    """Get latest quotes for multiple symbols."""
    if not symbols:
        return {}
    with get_db_readonly() as conn:
        placeholders = ",".join(["?"] * len(symbols))
        rows = conn.execute(
            f"""SELECT * FROM market_quotes 
                WHERE symbol IN ({placeholders}) 
                AND quote_timestamp = (
                    SELECT MAX(quote_timestamp) FROM market_quotes mq 
                    WHERE mq.symbol = market_quotes.symbol
                )""",
            symbols
        ).fetchall()
        return {r["symbol"]: dict(r) for r in rows}


# ============================================================
# ALERTS
# ============================================================

def insert_alert(trade_id, alert_type, severity, message):
    """Insert a new alert. Returns alert_id."""
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO alerts (trade_id, alert_type, severity, alert_message)
               VALUES (?, ?, ?, ?)""",
            (trade_id, alert_type, severity, message)
        )
        return cursor.lastrowid


def get_active_alerts():
    """Get all unresolved alerts ordered by severity."""
    severity_order = "CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'WARNING' THEN 2 ELSE 3 END"
    with get_db_readonly() as conn:
        return conn.execute(
            f"""SELECT a.*, t.underlying, t.strategy_type 
                FROM alerts a
                LEFT JOIN trades t ON a.trade_id = t.trade_id
                WHERE a.resolved_flag = 0 
                ORDER BY {severity_order}, a.alert_time DESC"""
        ).fetchall()


def resolve_alert(alert_id, note=None):
    """Mark an alert as resolved."""
    with get_db() as conn:
        conn.execute(
            """UPDATE alerts SET resolved_flag = 1, resolved_time = datetime('now'), resolved_note = ?
               WHERE alert_id = ?""",
            (note, alert_id)
        )


def get_alert_count_by_severity():
    """Get count of unresolved alerts by severity level."""
    with get_db_readonly() as conn:
        rows = conn.execute(
            """SELECT severity, COUNT(*) as count FROM alerts 
               WHERE resolved_flag = 0 GROUP BY severity"""
        ).fetchall()
        return {r["severity"]: r["count"] for r in rows}


# ============================================================
# TRADE SNAPSHOTS
# ============================================================

def insert_trade_snapshot(snapshot_data):
    """Insert a trade snapshot."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO trade_snapshots
               (trade_id, underlying_price, position_value, pnl, delta, theta,
                short_strike_distance, dte)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot_data['trade_id'],
                snapshot_data.get('underlying_price'),
                snapshot_data.get('position_value'),
                snapshot_data.get('pnl'),
                snapshot_data.get('delta'),
                snapshot_data.get('theta'),
                snapshot_data.get('short_strike_distance'),
                snapshot_data.get('dte'),
            )
        )


# ============================================================
# ANALYTICS QUERIES
# ============================================================

def get_portfolio_summary(account=None):
    """Get aggregate portfolio metrics."""
    with get_db_readonly() as conn:
        base_filter = ""
        params = []
        if account:
            base_filter = "AND account = ?"
            params = [account]

        # Active trades
        active = conn.execute(
            f"""SELECT COUNT(*) as count, 
                       COALESCE(SUM(unrealized_pnl), 0) as total_unrealized,
                       COALESCE(SUM(entry_credit_debit * 100), 0) as total_premium,
                       COALESCE(SUM(max_loss), 0) as total_risk
                FROM trades 
                WHERE status IN ('ACTIVE', 'PARTIALLY_CLOSED', 'ADJUSTED', 'ROLLED_OPEN')
                {base_filter}""",
            params
        ).fetchone()

        # Historical trades
        historical = conn.execute(
            f"""SELECT COUNT(*) as count,
                       COALESCE(SUM(realized_pnl), 0) as total_realized,
                       SUM(CASE WHEN result_tag = 'WIN' THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN result_tag = 'LOSS' THEN 1 ELSE 0 END) as losses
                FROM trades 
                WHERE status IN ('CLOSED_WIN', 'CLOSED_LOSS', 'EXPIRED_WORTHLESS',
                                  'ASSIGNED_RESOLVED', 'EXERCISED_RESOLVED', 'ROLLED_HISTORICAL')
                {base_filter}""",
            params
        ).fetchone()

        return {
            "active_count": active["count"],
            "total_unrealized": active["total_unrealized"],
            "total_premium": active["total_premium"],
            "total_risk": active["total_risk"],
            "historical_count": historical["count"],
            "total_realized": historical["total_realized"],
            "wins": historical["wins"],
            "losses": historical["losses"],
        }


def get_pnl_by_strategy(account=None):
    """Get realized P&L grouped by strategy type."""
    with get_db_readonly() as conn:
        query = """SELECT strategy_type, 
                          COUNT(*) as trade_count,
                          SUM(realized_pnl) as total_pnl,
                          AVG(realized_pnl) as avg_pnl,
                          SUM(CASE WHEN result_tag = 'WIN' THEN 1 ELSE 0 END) as wins
                   FROM trades 
                   WHERE status IN ('CLOSED_WIN', 'CLOSED_LOSS', 'EXPIRED_WORTHLESS',
                                     'ASSIGNED_RESOLVED', 'EXERCISED_RESOLVED')"""
        params = []
        if account:
            query += " AND account = ?"
            params.append(account)
        query += " GROUP BY strategy_type ORDER BY total_pnl DESC"
        return conn.execute(query, params).fetchall()


def get_pnl_by_ticker(account=None):
    """Get realized P&L grouped by underlying ticker."""
    with get_db_readonly() as conn:
        query = """SELECT underlying, 
                          COUNT(*) as trade_count,
                          SUM(realized_pnl) as total_pnl,
                          AVG(realized_pnl) as avg_pnl
                   FROM trades 
                   WHERE status IN ('CLOSED_WIN', 'CLOSED_LOSS', 'EXPIRED_WORTHLESS',
                                     'ASSIGNED_RESOLVED', 'EXERCISED_RESOLVED')"""
        params = []
        if account:
            query += " AND account = ?"
            params.append(account)
        query += " GROUP BY underlying ORDER BY total_pnl DESC"
        return conn.execute(query, params).fetchall()


def get_trades_expiring_soon(days=7, account=None):
    """Get active trades with legs expiring within N days."""
    with get_db_readonly() as conn:
        query = """SELECT DISTINCT t.* FROM trades t
                   JOIN trade_legs tl ON t.trade_id = tl.trade_id
                   WHERE t.status IN ('ACTIVE', 'PARTIALLY_CLOSED', 'ADJUSTED', 'ROLLED_OPEN')
                   AND tl.expiry IS NOT NULL
                   AND date(tl.expiry) <= date('now', '+' || ? || ' days')
                   AND tl.status = 'OPEN'"""
        params = [days]
        if account:
            query += " AND t.account = ?"
            params.append(account)
        query += " ORDER BY tl.expiry ASC"
        return conn.execute(query, params).fetchall()

# ============================================================
# YTD UPLOADS & BROKER TRANSACTIONS
# ============================================================

def get_account_master():
    """Get all accounts mapped in account_master."""
    with get_db_readonly() as conn:
        return conn.execute("SELECT * FROM account_master").fetchall()


def get_year_close_status():
    """Get archive status for all years."""
    with get_db_readonly() as conn:
        return conn.execute("SELECT * FROM year_close_status ORDER BY year DESC").fetchall()


def archive_year(year, closed_by="admin"):
    """Lock and archive a specific year."""
    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO year_close_status 
               (year, status, closed_datetime, closed_by, is_locked)
               VALUES (?, 'Closed', datetime('now'), ?, 1)""",
            (year, closed_by)
        )


def is_year_locked(year):
    """Check if a year is locked."""
    with get_db_readonly() as conn:
        row = conn.execute("SELECT is_locked FROM year_close_status WHERE year = ?", (year,)).fetchone()
        return bool(row and row["is_locked"])


def insert_transaction_upload_batch(broker_name, platform_name, account_number, upload_year, file_name, file_path, record_count):
    """Insert a new upload batch record. Returns batch_id."""
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO transaction_upload_batches
               (broker_name, platform_name, account_number, upload_year, file_name, file_path, record_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (broker_name, platform_name, account_number, upload_year, file_name, file_path, record_count)
        )
        return cursor.lastrowid


def delete_broker_transactions(account_number, transaction_year):
    """Delete all broker transactions for a specific account and year."""
    with get_db() as conn:
        conn.execute(
            "DELETE FROM broker_transactions WHERE account_number = ? AND transaction_year = ?",
            (account_number, transaction_year)
        )


def insert_broker_transactions_bulk(batch_id, account_number, transaction_year, rows):
    """Insert multiple broker transaction rows."""
    import math

    def _safe_num(v):
        """Coerce any value to a clean float — never NaN, None, or inf."""
        if v is None:
            return 0.0
        try:
            f = float(v)
            return 0.0 if (math.isnan(f) or math.isinf(f)) else f
        except (TypeError, ValueError):
            return 0.0

    with get_db() as conn:
        for row in rows:
            # Determine net amount: gain/loss worksheet has explicit gain_loss field
            net_amount = (
                row.get('gain_loss', None)       # Gain/loss worksheet
                if row.get('gain_loss') is not None
                else row.get('amount', 0) - row.get('fees', 0)  # Transaction history
            )
            realized_pl = row.get('gain_loss', row.get('realized_pl', 0)) or 0

            conn.execute(
                """INSERT INTO broker_transactions
                   (batch_id, broker_name, platform_name, account_number, transaction_year, transaction_date,
                    ticker, underlying, description, transaction_type, quantity, price,
                    gross_amount, fees, net_amount, realized_pl, open_close_flag, source_file_name)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    batch_id,
                    row.get('broker', ''),
                    row.get('broker', ''),
                    account_number,
                    transaction_year,
                    row.get('date', ''),
                    row.get('symbol', ''),
                    row.get('underlying', ''),
                    row.get('description', ''),
                    row.get('normalized_type', row.get('type', '')),
                    _safe_num(row.get('quantity', 0)),
                    _safe_num(row.get('price', 0)),
                    _safe_num(row.get('amount', row.get('cost_basis', 0))),
                    _safe_num(row.get('fees', 0)),
                    _safe_num(net_amount),
                    _safe_num(realized_pl),
                    row.get('open_close', 'CLOSE'),
                    row.get('source_file_name', '')
                )
            )


def get_broker_transactions(year=None, broker=None, account=None):
    """Get consolidated broker transactions."""
    with get_db_readonly() as conn:
        query = "SELECT * FROM broker_transactions WHERE 1=1"
        params = []
        if year:
            query += " AND transaction_year = ?"
            params.append(year)
        if broker:
            query += " AND broker_name = ?"
            params.append(broker)
        if account:
            query += " AND account_number = ?"
            params.append(account)
        query += " ORDER BY transaction_date DESC"
        return conn.execute(query, params).fetchall()
