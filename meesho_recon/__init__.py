"""Meesho seller payment reconciliation engine.

A clean-room reimplementation of the third-party Excel system analysed in
docs/REVERSE_ENGINEERING.md. Feed it raw Meesho downloads; it produces the
same SKU/State P&L reports, the shipping-overcharge export and the
pending-payment list, with every figure traceable to a documented rule.
"""
__version__ = "1.0.0"

from .config import Config          # noqa: F401
