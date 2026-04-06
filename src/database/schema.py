"""
Database Schema
Creates all tables for the portfolio management system.
"""

from src.database.connection import get_db


SCHEMA_SQL = """
-- ============================================================
-- RAW IMPORT FILES: Metadata about uploaded broker files
-- ============================================================
CREATE TABLE IF NOT EXISTS raw_import_files (
    import_id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    broker TEXT NOT NULL,
    upload_timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    file_hash TEXT NOT NULL UNIQUE,
    row_count INTEGER DEFAULT 0,
    processed_status TEXT DEFAULT 'pending',
    source_type TEXT DEFAULT 'file',  -- 'file' or 'api'
    notes TEXT
);

-- ============================================================
-- RAW TRANSACTIONS: Raw broker rows before normalization
-- ============================================================
CREATE TABLE IF NOT EXISTS raw_transactions (
    raw_txn_id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id INTEGER NOT NULL,
    raw_payload TEXT NOT NULL,  -- JSON blob of original row
    broker TEXT NOT NULL,
    source_row_number INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (import_id) REFERENCES raw_import_files(import_id)
);
CREATE INDEX IF NOT EXISTS idx_raw_txn_import ON raw_transactions(import_id);

-- ============================================================
-- NORMALIZED TRANSACTIONS: Broker-independent transaction model
-- ============================================================
CREATE TABLE IF NOT EXISTS normalized_transactions (
    txn_id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_txn_id INTEGER,
    broker TEXT NOT NULL,
    account TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    settlement_date TEXT,
    symbol TEXT NOT NULL,
    underlying TEXT NOT NULL,
    expiry TEXT,
    strike REAL,
    put_call TEXT,  -- 'P' or 'C'
    side TEXT NOT NULL,  -- 'BUY' or 'SELL'
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    fees REAL DEFAULT 0,
    multiplier INTEGER DEFAULT 100,
    txn_type TEXT NOT NULL,  -- 'TRADE', 'EXPIRATION', 'ASSIGNMENT', 'EXERCISE'
    open_close_flag TEXT,  -- 'OPEN', 'CLOSE'
    instrument_type TEXT DEFAULT 'EQUITY_OPTION',  -- 'EQUITY', 'EQUITY_OPTION'
    order_id TEXT,
    description TEXT,
    net_amount REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    dedup_hash TEXT UNIQUE,  -- SHA-256 for deduplication
    FOREIGN KEY (raw_txn_id) REFERENCES raw_transactions(raw_txn_id)
);
CREATE INDEX IF NOT EXISTS idx_norm_txn_underlying ON normalized_transactions(underlying);
CREATE INDEX IF NOT EXISTS idx_norm_txn_account ON normalized_transactions(account);
CREATE INDEX IF NOT EXISTS idx_norm_txn_date ON normalized_transactions(trade_date);
CREATE INDEX IF NOT EXISTS idx_norm_txn_symbol ON normalized_transactions(symbol);

-- ============================================================
-- TRADES: One row per grouped strategy
-- ============================================================
CREATE TABLE IF NOT EXISTS trades (
    trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_trade_id INTEGER,  -- For rolled trades
    roll_group_id TEXT,  -- Groups related rolls together
    account TEXT NOT NULL,
    broker TEXT NOT NULL,
    underlying TEXT NOT NULL,
    strategy_type TEXT NOT NULL,  -- 'PUT_CREDIT_SPREAD', 'IRON_CONDOR', etc.
    open_date TEXT NOT NULL,
    close_date TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    entry_credit_debit REAL DEFAULT 0,  -- Positive = credit, Negative = debit
    realized_pnl REAL DEFAULT 0,
    unrealized_pnl REAL DEFAULT 0,
    max_profit REAL,
    max_loss REAL,
    days_held INTEGER DEFAULT 0,
    result_tag TEXT,  -- 'WIN', 'LOSS', 'BREAKEVEN'
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (parent_trade_id) REFERENCES trades(trade_id)
);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_underlying ON trades(underlying);
CREATE INDEX IF NOT EXISTS idx_trades_account ON trades(account);
CREATE INDEX IF NOT EXISTS idx_trades_open_date ON trades(open_date);

-- ============================================================
-- TRADE LEGS: One row per option leg
-- ============================================================
CREATE TABLE IF NOT EXISTS trade_legs (
    leg_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    underlying TEXT NOT NULL,
    expiry TEXT,
    strike REAL,
    option_type TEXT,  -- 'P' or 'C'
    side TEXT NOT NULL,  -- 'LONG' or 'SHORT'
    qty_open REAL DEFAULT 0,
    qty_closed REAL DEFAULT 0,
    entry_price REAL DEFAULT 0,
    exit_price REAL,
    current_mark REAL,
    status TEXT NOT NULL DEFAULT 'OPEN',  -- 'OPEN', 'CLOSED', 'EXPIRED', 'ASSIGNED'
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
);
CREATE INDEX IF NOT EXISTS idx_legs_trade ON trade_legs(trade_id);
CREATE INDEX IF NOT EXISTS idx_legs_expiry ON trade_legs(expiry);
CREATE INDEX IF NOT EXISTS idx_legs_symbol ON trade_legs(symbol);

-- ============================================================
-- TRADE JOURNAL: Persistent notes per trade
-- ============================================================
CREATE TABLE IF NOT EXISTS trade_journal (
    journal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    note_type TEXT NOT NULL DEFAULT 'general',
    note_text TEXT NOT NULL,
    FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
);
CREATE INDEX IF NOT EXISTS idx_journal_trade ON trade_journal(trade_id);

-- ============================================================
-- MARKET QUOTES: Latest market snapshot (cached)
-- ============================================================
CREATE TABLE IF NOT EXISTS market_quotes (
    quote_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    quote_timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    underlying_price REAL,
    option_mark REAL,
    bid REAL,
    ask REAL,
    last REAL,
    delta REAL,
    gamma REAL,
    theta REAL,
    vega REAL,
    iv REAL,
    volume INTEGER,
    open_interest INTEGER
);
CREATE INDEX IF NOT EXISTS idx_quotes_symbol ON market_quotes(symbol);
CREATE INDEX IF NOT EXISTS idx_quotes_timestamp ON market_quotes(quote_timestamp);

-- ============================================================
-- TRADE SNAPSHOTS: Historical point-in-time snapshots
-- ============================================================
CREATE TABLE IF NOT EXISTS trade_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    snapshot_time TEXT NOT NULL DEFAULT (datetime('now')),
    underlying_price REAL,
    position_value REAL,
    pnl REAL,
    delta REAL,
    theta REAL,
    short_strike_distance REAL,
    dte INTEGER,
    FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_trade ON trade_snapshots(trade_id);

-- ============================================================
-- ALERTS: Active and historical alert events
-- ============================================================
CREATE TABLE IF NOT EXISTS alerts (
    alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER,
    alert_time TEXT NOT NULL DEFAULT (datetime('now')),
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'INFO',  -- 'INFO', 'WARNING', 'CRITICAL'
    alert_message TEXT NOT NULL,
    resolved_flag INTEGER DEFAULT 0,
    resolved_time TEXT,
    resolved_note TEXT,
    FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
);
CREATE INDEX IF NOT EXISTS idx_alerts_trade ON alerts(trade_id);
CREATE INDEX IF NOT EXISTS idx_alerts_resolved ON alerts(resolved_flag);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);

-- ============================================================
-- SETTINGS: Configurable thresholds and preferences
-- ============================================================
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Insert default settings
INSERT OR IGNORE INTO settings (key, value, description) VALUES
    ('profit_target_pct', '50', 'Profit target percentage to trigger alert'),
    ('dte_alert_days', '7', 'Days to expiry threshold for alerts'),
    ('strike_proximity_pct', '2', 'Short strike proximity percentage for alerts'),
    ('concentration_limit_pct', '25', 'Maximum ticker concentration percentage'),
    ('delta_exposure_limit', '100', 'Maximum net portfolio delta'),
    ('refresh_interval_sec', '300', 'Market data refresh interval in seconds'),
    ('tastytrade_environment', 'production', 'API environment: sandbox or production'),
    ('default_multiplier', '100', 'Default option contract multiplier');
"""


def init_database():
    """Initialize the database with full schema. Safe to call multiple times."""
    with get_db() as conn:
        conn.executescript(SCHEMA_SQL)


def reset_database():
    """Drop and recreate all tables. WARNING: Destroys all data."""
    drop_sql = """
    DROP TABLE IF EXISTS alerts;
    DROP TABLE IF EXISTS trade_snapshots;
    DROP TABLE IF EXISTS market_quotes;
    DROP TABLE IF EXISTS trade_journal;
    DROP TABLE IF EXISTS trade_legs;
    DROP TABLE IF EXISTS trades;
    DROP TABLE IF EXISTS normalized_transactions;
    DROP TABLE IF EXISTS raw_transactions;
    DROP TABLE IF EXISTS raw_import_files;
    DROP TABLE IF EXISTS settings;
    """
    with get_db() as conn:
        conn.executescript(drop_sql)
        conn.executescript(SCHEMA_SQL)
