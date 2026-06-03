import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
from src.market.yahoo_provider import YahooProvider
from src.utils.formatting import format_strength_meter

yp = YahooProvider()
symbols = ['SPY', 'QQQ', 'SPX', 'TSLA', 'AAPL']
print("Fetching daily metrics with Strength Meter...")
metrics = yp.get_daily_metrics_batch(symbols)
for sym, d in metrics.items():
    px   = d.get('price', 0) or 0
    prev = d.get('prev_close', 0) or 0
    nc   = d.get('net_change')
    atr  = d.get('atr')
    strength_pct = d.get('strength_pct')
    
    nc_str  = f"{nc:+.2f}" if nc is not None else "n/a"
    atr_str = f"{atr:.2f}" if atr else "n/a"
    
    if strength_pct is not None:
        strength_str = f"{strength_pct * 100:+.2f}%"
        bars, color = format_strength_meter(strength_pct)
        strength_display = f"{bars} ({strength_str})"
    else:
        strength_display = "n/a"
        
    print(f"{sym:6} | Last: {px:.2f} | PrevClose: {prev:.2f} | NetChange: {nc_str} | ATR: {atr_str} | Strength: {strength_display}")
