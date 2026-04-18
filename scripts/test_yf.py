import sys, os
sys.path.insert(0, '.')
from src.market.yahoo_provider import YahooProvider

yp = YahooProvider()
symbols = ['SPY', 'QQQ', 'SPX']
print("Fetching daily metrics...")
metrics = yp.get_daily_metrics_batch(symbols)
for sym, d in metrics.items():
    px   = d.get('price', 0) or 0
    prev = d.get('prev_close', 0) or 0
    nc   = d.get('net_change')
    atr  = d.get('atr')
    nc_str  = f"{nc:+.2f}" if nc is not None else "n/a"
    atr_str = f"{atr:.2f}" if atr else "n/a"
    print(f"{sym:6} | Last: {px:.2f} | PrevClose: {prev:.2f} | NetChange: {nc_str} | ATR: {atr_str}")
