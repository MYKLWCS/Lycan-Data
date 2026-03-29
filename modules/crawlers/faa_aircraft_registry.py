"""
faa_aircraft_registry.py — Re-export from transport subpackage.
"""

from modules.crawlers.transport.faa_aircraft_registry import FaaAircraftRegistryCrawler

__all__ = ["FaaAircraftRegistryCrawler"]
