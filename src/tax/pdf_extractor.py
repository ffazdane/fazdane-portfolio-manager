"""
Tax Center — PDF Extractor
===========================
Multi-strategy extraction from 1099-B / composite broker tax PDFs.

Strategy order (applied per file):
  1. TastyTrade/Apex text-line parser  (regex on raw text, 2-line transaction format)
  2. Schwab structured text parser     (regex on Schwab composite PDF layout)
  3. Futures/1099-B aggregate parser   (Line 8/9/10 regulated futures totals)
  4. Generic table parser              (pdfplumber table detection fallback)

All strategies return the same schema:
  {
    'broker', 'account', 'tax_year', 'source_file',
    'original_symbol', 'normalized_symbol', 'cusip', 'description',
    'date_acquired', 'date_sold', 'quantity',
    'proceeds', 'cost_basis', 'wash_sale_adj',
    'gain_loss', 'term',          # 'SHORT', 'LONG', 'UNKNOWN'
    'section_1256',               # bool
    'extraction_confidence',      # 'HIGH', 'MEDIUM', 'LOW'
    'review_note',
  }

No database writes. No file persistence.
"""

from __future__ import annotations
import io
import re
from collections import Counter
from typing import Any


# ── Shared helpers ────────────────────────────────────────────────────────────

def _clean(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip().replace("\n", " ")


def _parse_amount(val: Any) -> float | None:
    """Parse a dollar/number string, handling parentheses as negative."""
    s = _clean(val).replace(",", "").replace("$", "").strip()
    # (1,234.56) → -1234.56
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _extract_year_from_text(text: str) -> str:
    years = re.findall(r'\b(20[12]\d)\b', text)
    return Counter(years).most_common(1)[0][0] if years else ""


def _normalise_and_classify(symbol: str) -> tuple[str, bool]:
    """Return (normalised_symbol, is_section_1256)."""
    from src.tax.normalizer import normalise_ticker, is_section_1256
    norm = normalise_ticker(symbol) if symbol else ""
    s1256 = is_section_1256(symbol) if symbol else False
    return norm, s1256


def _build_txn(broker, account, tax_year, source_file,
               symbol_raw, cusip, desc, date_acq, date_sold,
               qty, proceeds, cost_basis, wash, gain_loss,
               term, confidence, note) -> dict:
    norm, s1256 = _normalise_and_classify(symbol_raw)
    if gain_loss is None and proceeds is not None and cost_basis is not None:
        gain_loss = round(proceeds - cost_basis + (wash or 0), 2)
    return {
        "broker":                broker,
        "account":               account,
        "tax_year":              tax_year,
        "source_file":           source_file,
        "original_symbol":       symbol_raw or "",
        "normalized_symbol":     norm,
        "cusip":                 cusip or "",
        "description":           desc or "",
        "date_acquired":         date_acq or "",
        "date_sold":             date_sold or "",
        "quantity":              qty,
        "proceeds":              proceeds or 0.0,
        "cost_basis":            cost_basis or 0.0,
        "wash_sale_adj":         wash or 0.0,
        "gain_loss":             gain_loss or 0.0,
        "term":                  term,
        "section_1256":          s1256,
        "extraction_confidence": confidence,
        "review_note":           note,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY 1: TastyTrade / Apex Clearing text-line parser
#
# Format (from 2025-5WT12803-irs_1099_tax.pdf):
#
#   CALL AMZN 10/17/25 230 AMAZON.COM INC | CUSIP: *8GPCCM3 | Symbol: AMZN--251017C00230000
#   2025-09-19  1  887.87  2025-09-15  896.12  0.00  -8.25
#
# The term context appears as section headers:
#   "SHORT-TERM TRANSACTIONS FOR COVERED TAX LOTS"
#   "LONG-TERM TRANSACTIONS FOR COVERED TAX LOTS"
# ═══════════════════════════════════════════════════════════════════════════════

# Header line: description | CUSIP: ... | Symbol: ...
_TT_HDR_RE = re.compile(
    r'^(?P<desc>.+?)\s*\|\s*CUSIP:\s*(?P<cusip>\S+)\s*\|\s*Symbol:\s*(?P<symbol>\S+)',
    re.IGNORECASE
)

# Data line: date_sold  qty  proceeds  date_acq  cost  wash  gain
_TT_DATA_RE = re.compile(
    r'^(?P<date_sold>\d{4}-\d{2}-\d{2})\s+'
    r'(?P<qty>[\d,]+(?:\.\d+)?)\s+'
    r'(?P<proceeds>[\d,]+\.\d{2})\s+'
    r'(?P<date_acq>\d{4}-\d{2}-\d{2})\s+'
    r'(?P<cost>[\d,]+\.\d{2})\s+'
    r'(?P<wash>[\d,]+\.\d{2})\s+'
    r'(?P<gain>-?[\d,]+\.\d{2})'
)

# Section totals line (skip)
_TT_TOTAL_RE = re.compile(r'Security Totals:', re.IGNORECASE)

# Term section headers
_TT_TERM_RE = re.compile(
    r'(SHORT[- ]TERM|LONG[- ]TERM|UNDETERMINED)',
    re.IGNORECASE
)


def _parse_tastytrade_text(all_text: str, broker: str, account: str,
                           tax_year: str, source_file: str) -> list[dict]:
    """Parse TastyTrade/Apex 1099-B text output."""
    transactions: list[dict] = []
    current_term = "UNKNOWN"
    pending_hdr: dict | None = None

    lines = all_text.splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Detect term context
        tm = _TT_TERM_RE.search(line)
        if tm:
            t = tm.group(1).upper().replace("-", "").replace(" ", "")
            if t.startswith("SHORT"):
                current_term = "SHORT"
            elif t.startswith("LONG"):
                current_term = "LONG"

        # Skip totals lines
        if _TT_TOTAL_RE.search(line):
            pending_hdr = None
            continue

        # Try header line
        hm = _TT_HDR_RE.match(line)
        if hm:
            pending_hdr = {
                "desc":   hm.group("desc").strip(),
                "cusip":  hm.group("cusip").strip(),
                "symbol": hm.group("symbol").strip(),
                "term":   current_term,
            }
            continue

        # Try data line
        if pending_hdr:
            dm = _TT_DATA_RE.match(line)
            if dm:
                sym = pending_hdr["symbol"]
                txn = _build_txn(
                    broker, account, tax_year, source_file,
                    symbol_raw=sym,
                    cusip=pending_hdr["cusip"],
                    desc=pending_hdr["desc"],
                    date_acq=dm.group("date_acq"),
                    date_sold=dm.group("date_sold"),
                    qty=_parse_amount(dm.group("qty")),
                    proceeds=_parse_amount(dm.group("proceeds")),
                    cost_basis=_parse_amount(dm.group("cost")),
                    wash=_parse_amount(dm.group("wash")),
                    gain_loss=_parse_amount(dm.group("gain")),
                    term=pending_hdr["term"],
                    confidence="HIGH",
                    note="",
                )
                transactions.append(txn)
                # Don't clear pending_hdr — next line could be another lot
                continue

    return transactions


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY 2: Regulated Futures 1099-B aggregate parser
#
# Format (2025-5WT12803-irs_1099b_tax.pdf):
#   8. Profit/(Loss) on Futures....... Converted to USD for OCT/25  763.32
#   -- Profit/(Loss) Realized on Futures Contracts in USD for 2025 (7,102.21)
#   11. Aggregate Profit or (Loss) from lines 8, 9 and 10 . . . (10,623.45)
#
# This file has NO individual transactions — only monthly/annual aggregates.
# We parse the annual totals as single synthetic summary rows.
# ═══════════════════════════════════════════════════════════════════════════════

_FUTURES_TOTAL_RE = re.compile(
    r'(?:--\s*)?(?P<label>Profit/\(Loss\) Realized on Futures (?:Contracts|Options))\s+'
    r'in USD for (?P<year>\d{4})\s+\(?(?P<amt>[\d,]+\.\d{2})\)?',
    re.IGNORECASE
)
_FUTURES_AGG_RE = re.compile(
    r'11\.\s+Aggregate Profit or \(Loss\).+?\.+\s*(?P<paren>\()?(?P<amt>[\d,]+\.\d{2})\)?',
    re.IGNORECASE
)
_FUTURES_LINE_RE = re.compile(
    r'Profit/\(Loss\) on Futures(?P<opts> Opts)?\.\.'
    r'.+?for (?P<month>[A-Z]{3}/\d{2})\s+(?P<paren>\()?(?P<amt>[\d,]+\.\d{2})\)?',
    re.IGNORECASE
)


def _parse_futures_1099b_text(all_text: str, broker: str, account: str,
                               tax_year: str, source_file: str) -> list[dict]:
    """Parse the Regulated Futures Contracts 1099-B aggregate format."""
    transactions: list[dict] = []

    # Total Futures P/L
    for m in _FUTURES_TOTAL_RE.finditer(all_text):
        raw = m.group("amt")
        amt = _parse_amount(raw)
        label = m.group("label")
        is_opts = "Options" in label

        # If the number appears in parentheses in the source, negate it
        # We check the surrounding text
        start = m.start()
        ctx = all_text[max(0, start-5):m.end()+5]
        if "(" in ctx.split(raw)[0][-5:]:
            amt = -(abs(amt)) if amt else amt

        symbol = "/MES" if not is_opts else "/MES_OPT"
        desc = f"{'Futures Options' if is_opts else 'Futures Contracts'} — Annual Total {m.group('year')}"
        txn = _build_txn(
            broker, account, m.group("year"), source_file,
            symbol_raw="ES" if not is_opts else "ES_OPT",
            cusip="", desc=desc,
            date_acq="", date_sold=f"{m.group('year')}-12-31",
            qty=None,
            proceeds=None, cost_basis=None, wash=0.0,
            gain_loss=amt,
            term="UNKNOWN",
            confidence="MEDIUM",
            note="Aggregate total from regulated futures 1099-B; Section 1256 treatment applies",
        )
        txn["section_1256"] = True
        transactions.append(txn)

    return transactions


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY 3: Schwab Composite text parser
#
# Schwab 1099 Composite has a summary table then detail sections.
# We parse the summary table lines like:
#   Short-term transactions for covered tax lots  146,215.24  150,249.98  0.00  0.00  -4,034.74
# And also detailed individual transactions (if present).
# ═══════════════════════════════════════════════════════════════════════════════

_SCHWAB_SUMMARY_RE = re.compile(
    r'(?P<section>Short-term|Long-term|Undetermined)\s+transactions\s+for\s+(?P<covered>covered|noncovered)\s+tax\s+lots'
    r'\s+(?P<proceeds>[\d,]+\.\d{2})\s+(?P<cost>[\d,]+\.\d{2})\s+(?P<mktdisc>[\d,.-]+)\s+(?P<wash>[\d,.-]+)\s+(?P<gain>-?[\d,]+\.\d{2})',
    re.IGNORECASE
)


def _parse_schwab_text(all_text: str, broker: str, account: str,
                       tax_year: str, source_file: str) -> list[dict]:
    """Parse Schwab 1099 Composite — summary level first, detail if available."""
    transactions: list[dict] = []

    # Summary rows
    for m in _SCHWAB_SUMMARY_RE.finditer(all_text):
        section = m.group("section").upper().replace("-", "")[:5]  # SHORT / LONG
        term = "SHORT" if "SHORT" in section else "LONG" if "LONG" in section else "UNKNOWN"
        covered = m.group("covered").lower()
        proceeds   = _parse_amount(m.group("proceeds"))
        cost       = _parse_amount(m.group("cost"))
        wash       = _parse_amount(m.group("wash")) or 0.0
        gain_loss  = _parse_amount(m.group("gain"))

        if proceeds == 0.0 and cost == 0.0:
            continue  # skip zero rows

        desc = f"{m.group('section').title()}-term {covered} tax lots summary"
        txn = _build_txn(
            broker, account, tax_year, source_file,
            symbol_raw="SCHWAB_SUMMARY",
            cusip="", desc=desc,
            date_acq="", date_sold=f"{tax_year}-12-31",
            qty=None,
            proceeds=proceeds, cost_basis=cost, wash=wash,
            gain_loss=gain_loss,
            term=term,
            confidence="MEDIUM",
            note="Summary-level row from Schwab composite; no per-ticker breakdown available here",
        )
        transactions.append(txn)

    # Also try individual detail lines (same format as TastyTrade/Apex if present)
    detail = _parse_tastytrade_text(all_text, broker, account, tax_year, source_file)
    transactions.extend(detail)

    return transactions


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY 4: Generic pdfplumber table fallback
# ═══════════════════════════════════════════════════════════════════════════════

HEADER_KEYWORDS = {"proceeds", "cost basis", "gain", "acquired", "sold", "description"}
PROCEEDS_KEYS   = {"proceeds", "gross proceeds", "sales price"}
COST_KEYS       = {"cost or other basis", "cost basis", "adjusted basis"}
GAIN_KEYS       = {"gain or loss", "gain/loss", "net gain", "realized"}
ACQUIRED_KEYS   = {"date acquired", "acquired", "date acq"}
SOLD_KEYS       = {"date sold", "sold", "date of sale"}
DESC_KEYS       = {"description", "security description", "name"}
CUSIP_KEYS      = {"cusip", "isin"}
QTY_KEYS        = {"quantity", "shares", "contracts", "qty"}
WASH_KEYS       = {"wash sale", "wash sale loss disallowed", "disallowed"}


def _is_header_row(row: list) -> bool:
    text = " ".join(_clean(c) for c in row if c).lower()
    return sum(1 for kw in HEADER_KEYWORDS if kw in text) >= 2


def _map_headers(headers: list[str]) -> dict[str, int]:
    m: dict[str, int] = {}
    for i, h in enumerate(headers):
        hl = h.lower().strip()
        if any(k in hl for k in PROCEEDS_KEYS):   m.setdefault("proceeds", i)
        if any(k in hl for k in COST_KEYS):        m.setdefault("cost_basis", i)
        if any(k in hl for k in GAIN_KEYS):        m.setdefault("gain_loss", i)
        if any(k in hl for k in ACQUIRED_KEYS):    m.setdefault("date_acquired", i)
        if any(k in hl for k in SOLD_KEYS):        m.setdefault("date_sold", i)
        if any(k in hl for k in DESC_KEYS):        m.setdefault("description", i)
        if any(k in hl for k in CUSIP_KEYS):       m.setdefault("cusip", i)
        if any(k in hl for k in QTY_KEYS):         m.setdefault("quantity", i)
        if any(k in hl for k in WASH_KEYS):        m.setdefault("wash_sale_adj", i)
    return m


def _extract_symbol_from_description(desc: str) -> str:
    occ = re.search(r'\b([A-Z]{1,6}W?\d{6}[CP]\d+)\b', desc)
    if occ:
        return occ.group(1)
    tokens = desc.strip().split()
    if tokens and re.match(r'^[A-Z]{1,8}$', tokens[0]):
        return tokens[0]
    return ""


def _parse_tables(pdf, broker: str, account: str, tax_year: str,
                  source_file: str) -> list[dict]:
    transactions: list[dict] = []
    current_term = "UNKNOWN"

    for page_num, page in enumerate(pdf.pages, 1):
        page_text = page.extract_text() or ""
        if "short-term" in page_text.lower():  current_term = "SHORT"
        if "long-term"  in page_text.lower():  current_term = "LONG"
        if "section 1256" in page_text.lower(): current_term = "UNKNOWN"  # handled separately

        for tbl in (page.extract_tables() or []):
            if not tbl:
                continue
            hdr_idx = next((ri for ri, row in enumerate(tbl) if row and _is_header_row(row)), None)
            if hdr_idx is None:
                continue
            col_map = _map_headers([_clean(c) for c in tbl[hdr_idx]])
            if not col_map:
                continue
            for row in tbl[hdr_idx + 1:]:
                if not row or all(_clean(c) == "" for c in row):
                    continue
                def _get(key: str) -> str:
                    idx = col_map.get(key)
                    return _clean(row[idx]) if idx is not None and idx < len(row) else ""
                desc      = _get("description")
                sym       = _extract_symbol_from_description(desc) or _get("cusip")
                proceeds  = _parse_amount(_get("proceeds"))
                cost      = _parse_amount(_get("cost_basis"))
                wash      = _parse_amount(_get("wash_sale_adj")) or 0.0
                gl        = _parse_amount(_get("gain_loss"))
                if proceeds is None and cost is None and gl is None:
                    continue
                filled = sum(1 for v in [sym, _get("date_sold"), proceeds, cost] if v)
                conf   = "HIGH" if filled >= 4 else "MEDIUM" if filled >= 2 else "LOW"
                transactions.append(_build_txn(
                    broker, account, tax_year, source_file,
                    symbol_raw=sym, cusip=_get("cusip"), desc=desc,
                    date_acq=_get("date_acquired"), date_sold=_get("date_sold"),
                    qty=_parse_amount(_get("quantity")),
                    proceeds=proceeds, cost_basis=cost, wash=wash, gain_loss=gl,
                    term=current_term,
                    confidence=conf,
                    note="Low-confidence extraction — verify against source PDF" if conf == "LOW" else "",
                ))
    return transactions


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def extract_from_pdf(
    pdf_bytes: bytes,
    filename: str,
    broker: str,
    account: str,
) -> tuple[list[dict], list[str]]:
    """
    Parse a 1099-B PDF and return (transactions, warnings).
    Tries multiple strategies and returns all results combined.
    """
    try:
        import pdfplumber
    except ImportError:
        return [], ["pdfplumber not installed — run: pip install pdfplumber"]

    transactions: list[dict] = []
    warnings: list[str] = []

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            # Extract all text once
            all_text = "\n".join(
                (page.extract_text() or "") for page in pdf.pages
            )
            tax_year = _extract_year_from_text(all_text) or "Unknown"

            fn_lower = filename.lower()

            # ── Strategy 1: TastyTrade/Apex individual option transactions
            tt_txns = _parse_tastytrade_text(all_text, broker, account, tax_year, filename)
            if tt_txns:
                transactions.extend(tt_txns)

            # ── Strategy 2: Regulated Futures aggregate (applies to 1099b_tax files)
            if "1099b" in fn_lower or "futures" in fn_lower or "regulated futures" in all_text.lower():
                fut_txns = _parse_futures_1099b_text(all_text, broker, account, tax_year, filename)
                if fut_txns:
                    transactions.extend(fut_txns)

            # ── Strategy 3: Schwab composite
            if broker.lower() == "schwab" or "_177" in filename.upper() or "XXX177" in filename.upper():
                schw_txns = _parse_schwab_text(all_text, broker, account, tax_year, filename)
                # Deduplicate against already-found tt_txns (Schwab also uses Apex format sometimes)
                existing_sigs = {
                    (t["date_sold"], t["proceeds"], t["cost_basis"]) for t in transactions
                }
                for t in schw_txns:
                    sig = (t["date_sold"], t["proceeds"], t["cost_basis"])
                    if sig not in existing_sigs:
                        transactions.append(t)
                        existing_sigs.add(sig)

            # ── Strategy 4: Generic table fallback (if nothing extracted yet)
            if not transactions:
                tbl_txns = _parse_tables(pdf, broker, account, tax_year, filename)
                transactions.extend(tbl_txns)

            if not transactions:
                warnings.append(
                    f"{filename}: No transactions extracted. "
                    "The PDF may be image-based (scanned), have a non-standard layout, "
                    "or contain only aggregate totals. "
                    "Check the 'Extraction Warnings' tab in the Excel report."
                )

    except Exception as e:
        warnings.append(f"{filename}: Extraction error — {e}")

    return transactions, warnings
