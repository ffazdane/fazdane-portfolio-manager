"""
Alert Engine
Generates and manages alerts based on configurable risk thresholds.
"""

from datetime import datetime
from src.database.queries import (
    insert_alert, get_active_alerts, resolve_alert,
    get_setting, get_alert_count_by_severity
)
from src.utils.option_symbols import calculate_dte


def evaluate_alerts(trade, risk_metrics, legs=None):
    """
    Evaluate all alert rules for a trade and create alerts as needed.
    Returns list of generated alert dicts.
    """
    alerts = []
    trade_id = trade['trade_id'] if isinstance(trade, dict) else trade[0]

    # 1. Short strike proximity
    alert = _check_strike_proximity(trade, risk_metrics, trade_id)
    if alert:
        alerts.append(alert)

    # 2. DTE threshold
    alert = _check_dte_threshold(trade, risk_metrics, trade_id)
    if alert:
        alerts.append(alert)

    # 3. Profit target reached
    alert = _check_profit_target(trade, risk_metrics, trade_id)
    if alert:
        alerts.append(alert)

    # 4. Spread value doubled (loss alert)
    alert = _check_spread_doubled(trade, risk_metrics, trade_id)
    if alert:
        alerts.append(alert)

    return alerts


def _check_strike_proximity(trade, metrics, trade_id):
    """Check if underlying is near the short strike."""
    dist_pct = metrics.get('short_strike_distance_pct')
    if dist_pct is None:
        return None

    threshold = float(get_setting('strike_proximity_pct', '2'))
    trade_dict = dict(trade) if not isinstance(trade, dict) else trade

    if abs(dist_pct) <= threshold:
        return _create_alert(
            trade_id,
            'STRIKE_BREACH',
            'CRITICAL',
            f"{trade_dict.get('underlying', '?')}: Short strike within {abs(dist_pct):.1f}% "
            f"(threshold: {threshold}%). Strike: {metrics.get('short_strike')}, "
            f"Underlying: ${metrics.get('underlying_price', 0):.2f}"
        )
    elif abs(dist_pct) <= threshold * 2.5:
        return _create_alert(
            trade_id,
            'STRIKE_WARNING',
            'WARNING',
            f"{trade_dict.get('underlying', '?')}: Short strike within {abs(dist_pct):.1f}% "
            f"(threshold: {threshold}%)"
        )
    return None


def _check_dte_threshold(trade, metrics, trade_id):
    """Check if DTE is below threshold."""
    dte = metrics.get('min_dte')
    if dte is None:
        return None

    threshold = int(get_setting('dte_alert_days', '7'))
    trade_dict = dict(trade) if not isinstance(trade, dict) else trade

    if dte <= 0:
        return _create_alert(
            trade_id,
            'EXPIRED',
            'CRITICAL',
            f"{trade_dict.get('underlying', '?')}: Position has EXPIRED (DTE: {dte})"
        )
    elif dte <= threshold:
        severity = 'CRITICAL' if dte <= 3 else 'WARNING'
        return _create_alert(
            trade_id,
            'DTE_LOW',
            severity,
            f"{trade_dict.get('underlying', '?')}: {dte} DTE remaining (threshold: {threshold})"
        )
    return None


def _check_profit_target(trade, metrics, trade_id):
    """Check if profit target has been reached."""
    profit_pct = metrics.get('profit_pct')
    if profit_pct is None:
        return None

    threshold = float(get_setting('profit_target_pct', '50'))
    trade_dict = dict(trade) if not isinstance(trade, dict) else trade

    if profit_pct >= threshold:
        return _create_alert(
            trade_id,
            'PROFIT_TARGET',
            'INFO',
            f"{trade_dict.get('underlying', '?')}: Profit target reached at {profit_pct:.1f}% "
            f"(target: {threshold}%)"
        )
    return None


def _check_spread_doubled(trade, metrics, trade_id):
    """Check if the spread value has doubled (significant loss)."""
    trade_dict = dict(trade) if not isinstance(trade, dict) else trade
    entry = trade_dict.get('entry_credit_debit', 0) or 0
    unrealized = trade_dict.get('unrealized_pnl', 0) or 0

    if entry > 0 and unrealized < -(entry * 100):
        return _create_alert(
            trade_id,
            'SPREAD_DOUBLED',
            'WARNING',
            f"{trade_dict.get('underlying', '?')}: Spread value has doubled. "
            f"Entry credit: ${entry:.2f}, Current loss: ${unrealized:.2f}"
        )
    return None


def _create_alert(trade_id, alert_type, severity, message):
    """Create and persist an alert."""
    alert_id = insert_alert(trade_id, alert_type, severity, message)
    return {
        'alert_id': alert_id,
        'trade_id': trade_id,
        'alert_type': alert_type,
        'severity': severity,
        'message': message,
    }


def get_all_active_alerts():
    """Get all unresolved alerts."""
    return get_active_alerts()


def acknowledge_alert(alert_id, note=None):
    """Mark an alert as resolved."""
    resolve_alert(alert_id, note)


def get_alert_summary():
    """Get alert counts by severity."""
    return get_alert_count_by_severity()
