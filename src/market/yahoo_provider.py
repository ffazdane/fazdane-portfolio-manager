"""
Yahoo Finance Fallback Provider
Used when tastytrade API is not available for underlying prices.

fast_info in modern yfinance is an object (not a dict) — must use getattr(), NOT .get().
Net change = today's last price − yesterday's close (from ticker.history()).
"""

from src.market.quote_provider import QuoteProvider


def _safe_float(obj, *attr_names, default=0.0):
    """
    Read the first matching attribute from a fast_info object (or plain dict),
    returning `default` on any failure.  Handles both attribute-style and
    dict-style access transparently.
    """
    for name in attr_names:
        try:
            # Attribute access (fast_info object, modern yfinance)
            val = getattr(obj, name, None)
            if val is not None and val == val:   # NaN check
                return float(val)
        except Exception:
            pass
        try:
            # Dict access (older yfinance / mocked objects)
            val = obj[name]
            if val is not None:
                return float(val)
        except Exception:
            pass
    return default


class YahooProvider(QuoteProvider):
    """Yahoo Finance fallback for underlying stock prices."""

    def _map_symbol(self, symbol):
        """Map standard indices to Yahoo Finance equivalents."""
        mapping = {
            'SPX': '^SPX',
            'NDX': '^NDX',
            'RUT': '^RUT',
            'VIX': '^VIX',
            'DJI': '^DJI'
        }
        return mapping.get(symbol.upper(), symbol)

    def get_underlying_price(self, symbol):
        """Get current price using yfinance fast_info (attribute access)."""
        try:
            import yfinance as yf
            ticker = yf.Ticker(self._map_symbol(symbol))
            info = ticker.fast_info
            return _safe_float(info, 'last_price', 'lastPrice') or None
        except Exception:
            return None

    def get_option_quote(self, symbol):
        """Yahoo doesn't provide real-time option quotes well — return None."""
        return None

    def get_batch_underlying_prices(self, symbols):
        """Get prices for multiple symbols."""
        prices = {}
        try:
            import yfinance as yf
            mapped_symbols = [self._map_symbol(s) for s in symbols]
            tickers = yf.Tickers(' '.join(mapped_symbols))

            for original_symbol, mapped_symbol in zip(symbols, mapped_symbols):
                try:
                    ticker = tickers.tickers.get(mapped_symbol.upper())
                    if ticker:
                        info = ticker.fast_info
                        price = _safe_float(info, 'last_price', 'lastPrice')
                        if price > 0:
                            prices[original_symbol] = price
                except Exception:
                    continue
        except Exception:
            pass
        return prices

    def get_daily_metrics_batch(self, symbols):
        """
        Get today's net change (vs yesterday's close), ATR(14), and last price
        for multiple symbols in one batch call.

        Net change = last_price − previous_close
        Previous close is read from ticker.history() row [-2] (most reliable
        source) with fast_info.previous_close as a fallback.
        """
        metrics = {}
        try:
            import yfinance as yf
            mapped_symbols = [self._map_symbol(s) for s in symbols]
            tickers = yf.Tickers(' '.join(mapped_symbols))

            for original_symbol, mapped_symbol in zip(symbols, mapped_symbols):
                try:
                    ticker = tickers.tickers.get(mapped_symbol.upper())
                    if not ticker:
                        continue

                    # ── Fetch 22 days of history: used for ATR(14) + prev close ──
                    hist = ticker.history(period="22d")

                    # ── Last price ──
                    info = ticker.fast_info
                    last_px = _safe_float(info, 'last_price', 'lastPrice')

                    # ── Yesterday's close (most reliable: second-to-last history row) ──
                    prev_close = 0.0
                    if not hist.empty and len(hist) >= 2:
                        # hist.index is date-sorted ascending; [-2] = yesterday's session
                        prev_close = float(hist['Close'].iloc[-2])
                    if prev_close == 0.0:
                        # Fallback: fast_info.previous_close attribute
                        prev_close = _safe_float(info, 'previous_close', 'previousClose')

                    # ── Net change vs yesterday's close ──
                    net_change = (last_px - prev_close) if (last_px > 0 and prev_close > 0) else None

                    # ── ATR(14) from True Range ──
                    atr = None
                    try:
                        if not hist.empty and len(hist) >= 15:
                            high_low    = hist['High'] - hist['Low']
                            high_close  = (hist['High'] - hist['Close'].shift(1)).abs()
                            low_close   = (hist['Low']  - hist['Close'].shift(1)).abs()
                            tr          = high_low.combine(high_close, max).combine(low_close, max)
                            atr         = float(tr.rolling(14).mean().iloc[-1])
                    except Exception:
                        pass

                    metrics[original_symbol] = {
                        'price':      last_px,
                        'prev_close': prev_close,
                        'net_change': net_change,
                        'atr':        atr,
                    }
                except Exception:
                    continue
        except Exception:
            pass
        return metrics

    def is_available(self):
        """Check if yfinance is importable."""
        try:
            import yfinance  # noqa: F401
            return True
        except ImportError:
            return False
