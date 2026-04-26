"""
Tax Center — Symbol Normalizer & Section 1256 Classifier
=========================================================
Rules:
  • SPXW  → SPX  (weekly SPX options)
  • NDX weekly → NDX
  • RUT weekly → RUT
  • Configurable SECTION_1256_TICKERS set

Section 1256 = 60% long-term / 40% short-term.
"""

from __future__ import annotations
import re

# ── Normalisation map ─────────────────────────────────────────────────────────
# Keys are exact uppercase original tickers; values are canonical names.
NORMALISE_MAP: dict[str, str] = {
    "SPXW":  "SPX",
    "NDXP":  "NDX",
    "RUTW":  "RUT",
    "VIXW":  "VIX",
    "XSPW":  "XSP",
    "DJXW":  "DJX",
}

# Prefixes whose weeklies collapse to the root (SPXW → SPX already handled above).
# These cover OCC-style symbols like "SPXW230120P04000000" → underlying = SPX
WEEKLY_PREFIX_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^SPXW"), "SPX"),
    (re.compile(r"^NDXP"), "NDX"),
    (re.compile(r"^RUTW"), "RUT"),
]

# ── Section 1256 candidates ───────────────────────────────────────────────────
# IRS § 1256: broad-based index options + regulated futures options.
# Final treatment must be confirmed against broker Form 6781 and tax advisor.
SECTION_1256_TICKERS: set[str] = {
    "SPX", "SPXW",
    "NDX", "NDXP",
    "RUT", "RUTW",
    "VIX", "VIXW",
    "XSP",  "DJX",
    # Common futures / micro-futures roots
    "ES",  "NQ",  "RTY", "YM",
    "MES", "MNQ", "M2K", "MYM",
    "/ES", "/NQ", "/RTY", "/YM",
    "/MES", "/MNQ", "/M2K", "/MYM",
}


def normalise_ticker(raw: str) -> str:
    """Return the canonical ticker for a raw symbol string."""
    if not raw:
        return raw
    raw = raw.strip().upper()

    # Direct map lookup
    if raw in NORMALISE_MAP:
        return NORMALISE_MAP[raw]

    # Weekly-prefix patterns
    for pat, canonical in WEEKLY_PREFIX_PATTERNS:
        if pat.match(raw):
            return canonical

    return raw


def is_section_1256(ticker: str) -> bool:
    """Return True if ticker qualifies as a Section 1256 candidate."""
    return normalise_ticker(ticker) in SECTION_1256_TICKERS or ticker.upper() in SECTION_1256_TICKERS


def split_6040(gain_loss: float) -> tuple[float, float]:
    """
    Apply 60/40 rule.
    Returns (long_term_60pct, short_term_40pct).
    """
    lt = round(gain_loss * 0.60, 2)
    st = round(gain_loss - lt, 2)
    return lt, st


# ── Broker / account detection from filename ─────────────────────────────────
ACCOUNT_BROKER_RULES: list[dict] = [
    {"pattern": "5WT12803",  "broker": "TastyTrade", "account": "5WT12803"},
    {"pattern": "XXX177",    "broker": "Schwab",      "account": "XXX177"},
    {"pattern": "_177",      "broker": "Schwab",      "account": "XXX177"},
]


def detect_broker_from_filename(filename: str) -> dict:
    """
    Detect broker and account from filename using global rules.
    Falls back to the shared ytd_validator function for DB-backed rules.
    Returns dict with 'broker', 'account', 'method'.
    """
    fn_upper = filename.upper()
    for rule in ACCOUNT_BROKER_RULES:
        if rule["pattern"].upper() in fn_upper:
            return {
                "broker":  rule["broker"],
                "account": rule["account"],
                "method":  "hardcoded_rule",
            }

    # Fall back to the shared DB-backed detector
    try:
        from src.ingestion.ytd_validator import detect_broker_and_account_from_filename
        return detect_broker_and_account_from_filename(filename)
    except Exception:
        return {"broker": "Unknown", "account": "Unknown", "method": None}
