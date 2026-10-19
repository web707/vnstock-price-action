"""
Layer 2 — Market Structure Builder Module.
Consumes exclusively swing points. Does not read candlesticks and does not import Layer 1.
"""

from structure_builder.builder import MarketStructureBuilder
from structure_builder.rules import RULE_VERSION, RULES_REGISTRY

__all__ = [
    "MarketStructureBuilder",
    "RULE_VERSION",
    "RULES_REGISTRY"
]
