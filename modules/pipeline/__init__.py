"""
Person Aggregation Pipeline.

Routes CrawlerResult objects into the correct DB tables,
linked to the right Person record.
"""

from modules.pipeline.aggregator import aggregate_result

__all__ = ["aggregate_result"]
