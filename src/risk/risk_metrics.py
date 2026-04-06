"""
Risk Metrics Calculator
Portfolio-level and trade-level risk calculations using live data.
"""

from datetime import datetime, date
from src.database.queries import get_active_trades, get_trade_legs, get_setting
from src.utils.option_symbols import calculate_dte


def calculate_trade_risk_metrics(trade, legs, underlying_price=None, greeks=None):
    """
    Calculate risk metrics for a single trade.
    Returns dict with all risk fields.
    """
    metrics = {
        'dte': None,
        'min_dte': None,
        'short_strike': None,
        'long_strike': None,
        'short_strike_distance': None,
        'short_strike_distance_pct': None,
        'spread_width': None,
        'net_delta': 0,
        'net_gamma': 0,
        'net_theta': 0,
        'net_vega': 0,
        'underlying_price': underlying_price,
        'profit_pct': None,
    }

    if not legs:
        return metrics

    # Calculate DTE from nearest expiry
    dtes = []
    short_strikes = []
    long_strikes = []

    for leg in legs:
        leg = dict(leg) if not isinstance(leg, dict) else leg
        dte = calculate_dte(leg.get('expiry'))
        if dte is not None:
            dtes.append(dte)

        # Collect strikes by side
        if leg.get('side') == 'SHORT' and leg.get('strike'):
            short_strikes.append(leg['strike'])
        elif leg.get('side') == 'LONG' and leg.get('strike'):
            long_strikes.append(leg['strike'])

        # Aggregate Greeks if available
        if greeks and leg.get('symbol') in greeks:
            g = greeks[leg['symbol']]
            qty = abs(leg.get('qty_open', 0) - leg.get('qty_closed', 0))
            sign = -1 if leg.get('side') == 'SHORT' else 1
            metrics['net_delta'] += (g.get('delta', 0) or 0) * qty * sign
            metrics['net_gamma'] += (g.get('gamma', 0) or 0) * qty * sign
            metrics['net_theta'] += (g.get('theta', 0) or 0) * qty * sign
            metrics['net_vega'] += (g.get('vega', 0) or 0) * qty * sign

    if dtes:
        metrics['min_dte'] = min(dtes)
        metrics['dte'] = min(dtes)

    # Short strike distance
    if short_strikes and underlying_price:
        # For puts, distance = underlying - short strike
        # For calls, distance = short strike - underlying
        put_short = [s for s, l in zip(short_strikes, legs)
                     if dict(l).get('option_type') == 'P' or dict(l).get('put_call') == 'P']
        call_short = [s for s, l in zip(short_strikes, legs)
                      if dict(l).get('option_type') == 'C' or dict(l).get('put_call') == 'C']

        nearest_distance = float('inf')
        nearest_strike = None

        for strike in put_short:
            dist = underlying_price - strike
            if abs(dist) < abs(nearest_distance):
                nearest_distance = dist
                nearest_strike = strike

        for strike in call_short:
            dist = strike - underlying_price
            if abs(dist) < abs(nearest_distance):
                nearest_distance = dist
                nearest_strike = strike

        if nearest_strike is not None:
            metrics['short_strike'] = nearest_strike
            metrics['short_strike_distance'] = nearest_distance
            if underlying_price > 0:
                metrics['short_strike_distance_pct'] = (nearest_distance / underlying_price) * 100

    if long_strikes:
        metrics['long_strike'] = sorted(long_strikes)[0]

    # Spread width
    if short_strikes and long_strikes:
        metrics['spread_width'] = abs(max(short_strikes + long_strikes) - min(short_strikes + long_strikes))

    # Profit percentage
    trade_dict = dict(trade) if not isinstance(trade, dict) else trade
    max_profit = trade_dict.get('max_profit')
    unrealized = trade_dict.get('unrealized_pnl', 0)
    if max_profit and max_profit > 0:
        metrics['profit_pct'] = (unrealized / max_profit) * 100

    return metrics


def calculate_portfolio_risk(trades_with_metrics):
    """
    Calculate portfolio-level risk aggregations.
    Input: list of (trade, metrics) tuples.
    """
    portfolio = {
        'total_delta': 0,
        'total_gamma': 0,
        'total_theta': 0,
        'total_vega': 0,
        'total_risk': 0,
        'expiring_this_week': 0,
        'breached_count': 0,
        'warning_count': 0,
        'concentration_by_ticker': {},
        'concentration_by_expiry': {},
    }

    for trade, metrics in trades_with_metrics:
        trade = dict(trade) if not isinstance(trade, dict) else trade
        portfolio['total_delta'] += metrics.get('net_delta', 0)
        portfolio['total_gamma'] += metrics.get('net_gamma', 0)
        portfolio['total_theta'] += metrics.get('net_theta', 0)
        portfolio['total_vega'] += metrics.get('net_vega', 0)
        portfolio['total_risk'] += abs(trade.get('max_loss', 0) or 0)

        # Expiring this week
        dte = metrics.get('min_dte')
        if dte is not None and dte <= 7:
            portfolio['expiring_this_week'] += 1

        # Breach detection
        dist_pct = metrics.get('short_strike_distance_pct')
        if dist_pct is not None:
            threshold = float(get_setting('strike_proximity_pct', '2'))
            if abs(dist_pct) <= threshold:
                portfolio['breached_count'] += 1
            elif abs(dist_pct) <= threshold * 2.5:
                portfolio['warning_count'] += 1

        # Concentration tracking
        underlying = trade.get('underlying', 'Unknown')
        risk = abs(trade.get('max_loss', 0) or 0)
        portfolio['concentration_by_ticker'][underlying] = \
            portfolio['concentration_by_ticker'].get(underlying, 0) + risk

    return portfolio
