"""
Tax Center — PDF Extractor
===========================
Reads uploaded 1099-B / composite tax PDF bytes and returns
a list of raw transaction dicts suitable for normalisation.

Strategy:
  1. Use pdfplumber to extract all tables from each page.
  2. Heuristically identify 1099-B sections by looking for header keywords.
  3. Parse each row into a common schema.
  4. Flag low-confidence records for review.

Returned schema per transaction:
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
"""

from __future__ import annotations
import io
import re
from typing import Any

# ── Column keyword sets ───────────────────────────────────────────────────────
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


def _clean(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip().replace("\n", " ")


def _parse_amount(val: Any) -> float | None:
    s = _clean(val).replace(",", "").replace("$", "").replace("(", "-").replace(")", "")
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _detect_term(row_dict: dict, row_text: str) -> str:
    """Detect SHORT / LONG / UNKNOWN from any term-related field or row text."""
    combined = (row_text + " ".join(str(v) for v in row_dict.values())).lower()
    if "long" in combined and "short" not in combined:
        return "LONG"
    if "short" in combined and "long" not in combined:
        return "SHORT"
    if "box a" in combined or "covered short" in combined:
        return "SHORT"
    if "box d" in combined or "covered long" in combined:
        return "LONG"
    return "UNKNOWN"


def _map_headers(headers: list[str]) -> dict[str, int]:
    """Map column names to indices using keyword sets."""
    mapping: dict[str, int] = {}
    for i, h in enumerate(headers):
        hl = h.lower().strip()
        if any(k in hl for k in PROCEEDS_KEYS):
            mapping.setdefault("proceeds", i)
        if any(k in hl for k in COST_KEYS):
            mapping.setdefault("cost_basis", i)
        if any(k in hl for k in GAIN_KEYS):
            mapping.setdefault("gain_loss", i)
        if any(k in hl for k in ACQUIRED_KEYS):
            mapping.setdefault("date_acquired", i)
        if any(k in hl for k in SOLD_KEYS):
            mapping.setdefault("date_sold", i)
        if any(k in hl for k in DESC_KEYS):
            mapping.setdefault("description", i)
        if any(k in hl for k in CUSIP_KEYS):
            mapping.setdefault("cusip", i)
        if any(k in hl for k in QTY_KEYS):
            mapping.setdefault("quantity", i)
        if any(k in hl for k in WASH_KEYS):
            mapping.setdefault("wash_sale_adj", i)
    return mapping


def _is_header_row(row: list) -> bool:
    text = " ".join(_clean(c) for c in row).lower()
    matches = sum(1 for kw in HEADER_KEYWORDS if kw in text)
    return matches >= 2


def _extract_symbol_from_description(desc: str) -> str:
    """Attempt to pull a ticker from a text description."""
    # Try to find an OCC-style option symbol first
    occ = re.search(r'\b([A-Z]{1,6}W?\d{6}[CP]\d+)\b', desc)
    if occ:
        return occ.group(1)
    # Fall back to first word of ALL CAPS token
    tokens = desc.strip().split()
    if tokens and re.match(r'^[A-Z]{1,8}$', tokens[0]):
        return tokens[0]
    return ""


def _extract_year_from_text(text: str) -> str:
    """Find the most common 4-digit year in a text block."""
    years = re.findall(r'\b(20[12]\d)\b', text)
    if years:
        from collections import Counter
        return Counter(years).most_common(1)[0][0]
    return ""


def extract_from_pdf(
    pdf_bytes: bytes,
    filename: str,
    broker: str,
    account: str,
) -> tuple[list[dict], list[str]]:
    """
    Parse a 1099-B PDF and return (transactions, warnings).

    Parameters
    ----------
    pdf_bytes : raw bytes of the uploaded PDF
    filename  : original filename (for source tracking)
    broker    : pre-detected broker name
    account   : pre-detected account number

    Returns
    -------
    transactions : list of transaction dicts (see module docstring)
    warnings     : list of human-readable warning strings
    """
    try:
        import pdfplumber
    except ImportError:
        return [], ["pdfplumber not installed — pip install pdfplumber"]

    transactions: list[dict] = []
    warnings: list[str] = []

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            all_text = "\n".join(p.text or "" for p in pdf.pages)
            tax_year = _extract_year_from_text(all_text) or "Unknown"

            current_term = "UNKNOWN"
            found_1099 = False

            for page_num, page in enumerate(pdf.pages, 1):
                page_text = page.text or ""

                # Detect term context from page text
                if "short-term" in page_text.lower():
                    current_term = "SHORT"
                if "long-term" in page_text.lower():
                    current_term = "LONG"
                if "section 1256" in page_text.lower() or "form 6781" in page_text.lower():
                    current_term = "SEC1256"

                tables = page.extract_tables() or []
                for tbl in tables:
                    if not tbl:
                        continue

                    # Find header row
                    hdr_idx = None
                    for ri, row in enumerate(tbl):
                        if row and _is_header_row(row):
                            hdr_idx = ri
                            found_1099 = True
                            break

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

                        desc        = _get("description")
                        symbol_raw  = _extract_symbol_from_description(desc)
                        cusip       = _get("cusip")
                        date_acq    = _get("date_acquired")
                        date_sold   = _get("date_sold")
                        qty         = _parse_amount(_get("quantity"))
                        proceeds    = _parse_amount(_get("proceeds"))
                        cost_basis  = _parse_amount(_get("cost_basis"))
                        wash        = _parse_amount(_get("wash_sale_adj")) or 0.0
                        gain_loss   = _parse_amount(_get("gain_loss"))

                        # Skip if no financial data at all
                        if proceeds is None and cost_basis is None and gain_loss is None:
                            continue

                        # Compute gain/loss if not explicit
                        if gain_loss is None and proceeds is not None and cost_basis is not None:
                            gain_loss = round(proceeds - cost_basis + wash, 2)

                        # Confidence rating
                        filled = sum(1 for v in [symbol_raw, date_sold, proceeds, cost_basis] if v)
                        confidence = "HIGH" if filled >= 4 else "MEDIUM" if filled >= 2 else "LOW"
                        note = ""
                        if confidence == "LOW":
                            note = "Low-confidence extraction — verify against source PDF"
                            warnings.append(
                                f"Page {page_num}: Low-confidence row — {desc[:60] or '(no description)'}"
                            )

                        # Term override if page context is section 1256
                        term = current_term if current_term != "SEC1256" else "UNKNOWN"

                        from src.tax.normalizer import normalise_ticker, is_section_1256
                        normalised = normalise_ticker(symbol_raw) if symbol_raw else ""
                        sec1256 = is_section_1256(symbol_raw) if symbol_raw else (
                            current_term == "SEC1256"
                        )

                        transactions.append({
                            "broker":                broker,
                            "account":               account,
                            "tax_year":              tax_year,
                            "source_file":           filename,
                            "original_symbol":       symbol_raw,
                            "normalized_symbol":     normalised,
                            "cusip":                 cusip,
                            "description":           desc,
                            "date_acquired":         date_acq,
                            "date_sold":             date_sold,
                            "quantity":              qty,
                            "proceeds":              proceeds or 0.0,
                            "cost_basis":            cost_basis or 0.0,
                            "wash_sale_adj":         wash,
                            "gain_loss":             gain_loss or 0.0,
                            "term":                  term,
                            "section_1256":          sec1256,
                            "extraction_confidence": confidence,
                            "review_note":           note,
                        })

            if not found_1099:
                warnings.append(
                    f"{filename}: No 1099-B table detected — file may be unsupported or "
                    "text-only. Try a text-extractable PDF."
                )

    except Exception as e:
        warnings.append(f"{filename}: Extraction failed — {e}")

    return transactions, warnings
