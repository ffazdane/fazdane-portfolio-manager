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

    def is_available(self):
        """Check if yfinance is importable."""
        try:
            import yfinance
            return True
        except ImportError:
            return False
