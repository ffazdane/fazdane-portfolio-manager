"""
Abstract Broker Parser Interface
All broker-specific parsers must implement this interface.
"""

from abc import ABC, abstractmethod


class BrokerParser(ABC):
    """Base class for broker file parsers."""

    @abstractmethod
    def get_broker_name(self):
        """Return the broker name string."""
        pass

    @abstractmethod
    def detect(self, df):
        """
        Check if a DataFrame looks like it came from this broker.
        Returns True if the columns match this broker's format.
        """
        pass

    @abstractmethod
    def parse(self, df):
        """
        Parse a DataFrame into a list of raw transaction dicts.
        Each dict represents one transaction row with broker-specific fields.
        Returns list of dicts.
        """
        pass

    @abstractmethod
    def get_expected_columns(self):
        """Return list of expected column names for this broker."""
        pass
