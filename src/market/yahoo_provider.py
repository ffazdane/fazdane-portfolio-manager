"""
Yahoo Finance Fallback Provider
Used when tastytrade API is not available for underlying prices.
"""

from src.market.quote_provider import QuoteProvider


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
        """Get current price using yfinance."""
        try:
            import yfinance as yf
            ticker = yf.Ticker(self._map_symbol(symbol))
            info = ticker.fast_info
            return float(info.get('lastPrice', 0) or info.get('last_price', 0))
        except Exception:
            return None

    def get_option_quote(self, symbol):
        """Yahoo doesn't provide real-time option quotes well - return None."""
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
                        price = float(info.get('lastPrice', 0) or info.get('last_price', 0))
                        if price > 0:
                            prices[original_symbol] = price
                except Exception:
                    continue
        except Exception:
            pass
        return prices

    def get_daily_metrics_batch(self, symbols):
        """Get net change and ATR for multiple symbols."""
        metrics = {}
        try:
            import yfinance as yf
            mapped_symbols = [self._map_symbol(s) for s in symbols]
            tickers = yf.Tickers(' '.join(mapped_symbols))

            for original_symbol, mapped_symbol in zip(symbols, mapped_symbols):
                try:
                    ticker = tickers.tickers.get(mapped_symbol.upper())
                    if ticker:
                        info = ticker.fast_info
                        last_px = float(info.get('lastPrice', 0) or info.get('last_price', 0))
                        prev_px = float(info.get('previousClose', 0) or info.get('previous_close', 0))
                        net_change = last_px - prev_px if prev_px > 0 else 0
                        
                        atr = None
                        try:
                            hist = ticker.history(period="20d")
                            if not hist.empty:
                                high_low = hist['High'] - hist['Low']
                                high_close = (hist['High'] - hist['Close'].shift()).abs()
                                low_close = (hist['Low'] - hist['Close'].shift()).abs()
                                tr = high_low.combine(high_close, max).combine(low_close, max)
                                atr = float(tr.rolling(14).mean().iloc[-1])
                        except Exception:
                            pass
                        
                        metrics[original_symbol] = {
                            'net_change': net_change,
                            'atr': atr,
                            'price': last_px
                        }
                except Exception:
                    continue
        except Exception:
            pass
        return metrics

    def is_available(self):
        """Check if yfinance is importable."""
        try:
            import yfinance
            return True
        except ImportError:
            return False
