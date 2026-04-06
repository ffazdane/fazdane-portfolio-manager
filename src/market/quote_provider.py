"""
Quote Provider Interface
Abstract interface for market data providers.
"""

from abc import ABC, abstractmethod


class QuoteProvider(ABC):
    """Abstract interface for market data sources."""

    @abstractmethod
    def get_underlying_price(self, symbol):
        """Get the current price of an underlying. Returns float or None."""
        pass

    @abstractmethod
    def get_option_quote(self, symbol):
        """Get option quote data. Returns dict with bid, ask, mark, greeks."""
        pass

    @abstractmethod
    def get_batch_underlying_prices(self, symbols):
        """Get prices for multiple underlyings. Returns dict {symbol: price}."""
        pass

    @abstractmethod
    def is_available(self):
        """Check if this provider is available and connected."""
        pass
