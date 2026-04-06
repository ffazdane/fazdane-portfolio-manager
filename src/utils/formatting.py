"""
Display Formatting Helpers
Currency, P&L, percentages, dates, and Greeks formatting for the UI.
"""

from datetime import datetime


def format_currency(value, include_sign=False):
    """Format a number as currency."""
    if value is None:
        return "—"
    try:
        value = float(value)
        if include_sign:
            return f"${value:+,.2f}"
        return f"${value:,.2f}"
    except (ValueError, TypeError):
        return "—"


def format_pnl(value):
    """Format P&L with sign and color indicator."""
    if value is None:
        return "—", "neutral"
    try:
        value = float(value)
        formatted = f"${value:+,.2f}"
        color = "green" if value > 0 else "red" if value < 0 else "neutral"
        return formatted, color
    except (ValueError, TypeError):
        return "—", "neutral"


def format_pnl_html(value):
    """Format P&L as colored HTML."""
    if value is None:
        return '<span style="color: #888;">—</span>'
    try:
        value = float(value)
        color = "#00D4AA" if value > 0 else "#FF4B4B" if value < 0 else "#888"
        return f'<span style="color: {color}; font-weight: 600;">${value:+,.2f}</span>'
    except (ValueError, TypeError):
        return '<span style="color: #888;">—</span>'


def format_percentage(value, decimals=1):
    """Format a number as percentage."""
    if value is None:
        return "—"
    try:
        value = float(value)
        return f"{value:+.{decimals}f}%"
    except (ValueError, TypeError):
        return "—"


def format_dte(dte):
    """Format days to expiry with urgency context."""
    if dte is None:
        return "—", "neutral"
    try:
        dte = int(dte)
        if dte <= 0:
            return "EXPIRED", "critical"
        elif dte <= 7:
            return f"{dte}d", "critical"
        elif dte <= 21:
            return f"{dte}d", "warning"
        else:
            return f"{dte}d", "normal"
    except (ValueError, TypeError):
        return "—", "neutral"


def format_date(date_str, fmt='%m/%d/%y'):
    """Format a date string for display."""
    if not date_str:
        return "—"
    try:
        if isinstance(date_str, str):
            dt = datetime.strptime(date_str[:10], '%Y-%m-%d')
        elif isinstance(date_str, datetime):
            dt = date_str
        else:
            return str(date_str)
        return dt.strftime(fmt)
    except (ValueError, TypeError):
        return str(date_str)


def format_delta(value):
    """Format delta value."""
    if value is None:
        return "—"
    try:
        return f"{float(value):+.2f}"
    except (ValueError, TypeError):
        return "—"


def format_theta(value):
    """Format theta (daily decay) value."""
    if value is None:
        return "—"
    try:
        return f"{float(value):+.4f}"
    except (ValueError, TypeError):
        return "—"


def format_greek(value, decimals=4):
    """Format a Greek value."""
    if value is None:
        return "—"
    try:
        return f"{float(value):+.{decimals}f}"
    except (ValueError, TypeError):
        return "—"


def format_strike_distance(underlying_price, short_strike, is_put=True):
    """Format distance from underlying to short strike."""
    if underlying_price is None or short_strike is None:
        return "—", "neutral"
    try:
        underlying_price = float(underlying_price)
        short_strike = float(short_strike)
        if underlying_price == 0:
            return "—", "neutral"

        if is_put:
            distance = underlying_price - short_strike
        else:
            distance = short_strike - underlying_price

        pct = (distance / underlying_price) * 100
        severity = "critical" if pct < 2 else "warning" if pct < 5 else "normal"
        return f"${distance:+.2f} ({pct:+.1f}%)", severity
    except (ValueError, TypeError):
        return "—", "neutral"


def format_quantity(qty):
    """Format a quantity value."""
    if qty is None:
        return "—"
    try:
        qty = float(qty)
        if qty == int(qty):
            return str(int(qty))
        return f"{qty:.2f}"
    except (ValueError, TypeError):
        return "—"


def status_badge(status):
    """Get an emoji badge for a trade status."""
    badges = {
        'ACTIVE': '🟢',
        'PARTIALLY_CLOSED': '🟡',
        'ADJUSTED': '🔵',
        'ROLLED_OPEN': '🔄',
        'CLOSED_WIN': '✅',
        'CLOSED_LOSS': '❌',
        'EXPIRED_WORTHLESS': '💀',
        'ASSIGNED_RESOLVED': '📋',
        'EXERCISED_RESOLVED': '📋',
        'ROLLED_HISTORICAL': '📦',
    }
    return badges.get(status, '⚪')


def severity_badge(severity):
    """Get styled badge for alert severity."""
    badges = {
        'CRITICAL': '🔴',
        'WARNING': '🟡',
        'INFO': '🔵',
    }
    return badges.get(severity, '⚪')


def strategy_display_name(strategy_type):
    """Convert strategy type constant to display name."""
    names = {
        'PUT_CREDIT_SPREAD': 'Put Credit Spread',
        'CALL_CREDIT_SPREAD': 'Call Credit Spread',
        'PUT_DEBIT_SPREAD': 'Put Debit Spread',
        'CALL_DEBIT_SPREAD': 'Call Debit Spread',
        'IRON_CONDOR': 'Iron Condor',
        'IRON_BUTTERFLY': 'Iron Butterfly',
        'CALENDAR_SPREAD': 'Calendar Spread',
        'DIAGONAL_SPREAD': 'Diagonal Spread',
        'SINGLE_PUT': 'Single Put',
        'SINGLE_CALL': 'Single Call',
        'CUSTOM': 'Custom Multi-Leg',
        'EQUITY': 'Stock/ETF',
    }
    return names.get(strategy_type, strategy_type.replace('_', ' ').title())


def note_type_display(note_type):
    """Get display label and emoji for journal note types."""
    types = {
        'entry_thesis': ('📝 Entry Thesis', '#00D4AA'),
        'adjustment_note': ('🔧 Adjustment', '#FFA500'),
        'warning_note': ('⚠️ Warning', '#FF4B4B'),
        'exit_reason': ('🚪 Exit Reason', '#888'),
        'lesson_learned': ('🎓 Lesson Learned', '#9370DB'),
        'emotional_note': ('💭 Emotional Note', '#FFD700'),
        'market_context': ('📊 Market Context', '#4169E1'),
        'post_trade_review': ('🔍 Post-Trade Review', '#20B2AA'),
        'general': ('📌 Note', '#FAFAFA'),
    }
    return types.get(note_type, ('📌 Note', '#FAFAFA'))
