"""Statistical anomaly detection — pure Python, no ML dependencies."""
import logging
import math
import statistics
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AnomalyResult:
    entity_id: str
    field: str
    value: float
    z_score: float
    is_anomaly: bool
    severity: str  # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    reason: str


class StatisticalAnomalyDetector:
    """
    Detects univariate anomalies using Z-score and IQR methods.

    No external dependencies. Works on any numeric field across a list of entity dicts.
    """

    def __init__(self, z_threshold: float = 3.0, iqr_multiplier: float = 1.5) -> None:
        self.z_threshold = z_threshold
        self.iqr_multiplier = iqr_multiplier

    def detect(self, entities: list[dict], field: str) -> list[AnomalyResult]:
        """
        Detect anomalies in `field` across a list of entity dicts.

        Entities without the field or with non-numeric values are skipped.
        Returns only anomalous entities, sorted by z_score descending.
        """
        # Extract (entity_id, value) pairs
        pairs: list[tuple[str, float]] = []
        for e in entities:
            val = e.get(field)
            try:
                pairs.append((str(e.get("id", "")), float(val)))
            except (TypeError, ValueError):
                continue

        if len(pairs) < 3:
            return []

        values = [v for _, v in pairs]

        # Compute Z-score stats
        mean = statistics.mean(values)
        try:
            stdev = statistics.stdev(values)
        except statistics.StatisticsError:
            stdev = 0.0

        # Compute IQR
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        q1 = sorted_vals[n // 4]
        q3 = sorted_vals[(3 * n) // 4]
        iqr = q3 - q1
        lower_fence = q1 - self.iqr_multiplier * iqr
        upper_fence = q3 + self.iqr_multiplier * iqr

        results: list[AnomalyResult] = []
        for entity_id, val in pairs:
            z = abs((val - mean) / stdev) if stdev > 0 else 0.0
            iqr_outlier = val < lower_fence or val > upper_fence
            is_anomaly = z > self.z_threshold or iqr_outlier

            if not is_anomaly:
                continue

            # Severity from z_score
            if z > 6.0:
                severity = "CRITICAL"
            elif z > 4.5:
                severity = "HIGH"
            elif z > 3.0:
                severity = "MEDIUM"
            else:
                severity = "LOW"

            reasons = []
            if z > self.z_threshold:
                reasons.append(f"Z-score={z:.2f} (threshold={self.z_threshold})")
            if iqr_outlier:
                reasons.append(f"IQR outlier (fence [{lower_fence:.2f}, {upper_fence:.2f}])")

            results.append(AnomalyResult(
                entity_id=entity_id,
                field=field,
                value=val,
                z_score=round(z, 4),
                is_anomaly=True,
                severity=severity,
                reason="; ".join(reasons),
            ))

        results.sort(key=lambda r: r.z_score, reverse=True)
        return results

    def detect_multi_field(
        self, entities: list[dict], fields: list[str]
    ) -> dict[str, list[AnomalyResult]]:
        """Run anomaly detection across multiple fields. Returns field → results."""
        return {f: self.detect(entities, f) for f in fields}
