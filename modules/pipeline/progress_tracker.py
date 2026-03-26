"""
Progress tracking for real-time search monitoring.

ProgressCalculator  — pure math: phase % → overall %
ProgressAggregator  — stateful: processes events, tracks scraper statuses
"""

from datetime import datetime
from typing import Optional

from shared.schemas.progress import EventType, Phase, ProgressState

# Phase boundary definitions: {phase: (start_pct, end_pct)}
PHASE_RANGES: dict[str, tuple[float, float]] = {
    Phase.COLLECTING: (0.0, 60.0),
    Phase.DEDUPLICATING: (60.0, 75.0),
    Phase.ENRICHING: (75.0, 95.0),
    Phase.FINALIZING: (95.0, 100.0),
    Phase.COMPLETE: (100.0, 100.0),
}


class ProgressCalculator:
    """Pure calculation — no state."""

    def __init__(self, start_time: datetime, scraper_count: int) -> None:
        self.start_time = start_time
        self.scraper_count = max(1, scraper_count)

    def collection_pct(self, completed: int, failed: int) -> float:
        done = completed + failed
        return min(60.0, (done / self.scraper_count) * 60.0)

    def dedup_pct(self, processed: int, total: int) -> float:
        if total == 0:
            return 60.0
        return 60.0 + min(15.0, (processed / total) * 15.0)

    def enrichment_pct(self, completed: int, total: int) -> float:
        if total == 0:
            return 75.0
        return 75.0 + min(20.0, (completed / total) * 20.0)

    def overall_pct(self, phase: str, phase_value: float) -> float:
        """Map a raw phase value (already in overall %) to overall %."""
        return min(100.0, max(0.0, phase_value))

    def estimate_remaining(
        self,
        current_pct: float,
        phase_start_time: datetime,
        current_phase: str,
    ) -> float:
        elapsed_total = (datetime.utcnow() - self.start_time).total_seconds()
        elapsed_phase = (datetime.utcnow() - phase_start_time).total_seconds()

        # Linear extrapolation from overall progress
        if current_pct > 0:
            linear_remaining = (elapsed_total / current_pct) * 100.0 - elapsed_total
        else:
            linear_remaining = 300.0  # default 5-min estimate when at 0%

        # Phase-based estimate
        p_start, p_end = PHASE_RANGES.get(current_phase, (0.0, 100.0))
        p_range = p_end - p_start
        p_progress = current_pct - p_start

        if p_progress > 0 and p_range > 0:
            phase_pct = p_progress / p_range
            phase_remaining = (elapsed_phase / max(0.01, phase_pct)) - elapsed_phase
        else:
            phase_remaining = linear_remaining

        # Average both estimates, clamp to 0–3600 s
        combined = (linear_remaining + phase_remaining) / 2.0
        return max(0.0, min(3600.0, combined))


class ProgressAggregator:
    """
    Stateful aggregator: receives raw events from Redis pub/sub and
    maintains the current ProgressState for the SSE endpoint to emit.
    """

    def __init__(self, search_id: str, scraper_count: int = 1) -> None:
        self.search_id = search_id
        self.start_time = datetime.utcnow()
        self.phase_start_time = datetime.utcnow()
        self.calc = ProgressCalculator(self.start_time, scraper_count)

        self.current_phase: str = Phase.COLLECTING
        self.scraper_statuses: dict[str, str] = {}
        self.scrapers_completed = 0
        self.scrapers_failed = 0
        self.results_found = 0

        # Dedup / enrichment tracking
        self._dedup_processed = 0
        self._dedup_total = 0
        self._enrich_completed = 0
        self._enrich_total = 0

    # ------------------------------------------------------------------
    def process(self, event: dict) -> Optional[ProgressState]:
        """
        Update internal state from a raw event dict.
        Returns the new ProgressState (always, for immediate SSE emit).
        """
        etype = event.get("event_type", "")

        if etype == EventType.SEARCH_STARTED:
            total = event.get("total_scrapers", 1)
            self.calc = ProgressCalculator(self.start_time, total)
            # Pre-populate all scrapers as queued
            for name in event.get("scrapers", []):
                self.scraper_statuses[name] = "queued"

        elif etype == EventType.SCRAPER_QUEUED:
            name = event.get("scraper_name", "")
            if name:
                self.scraper_statuses[name] = "queued"

        elif etype == EventType.SCRAPER_RUNNING:
            name = event.get("scraper_name", "")
            if name:
                self.scraper_statuses[name] = "running"

        elif etype == EventType.SCRAPER_DONE:
            name = event.get("scraper_name", "")
            if name:
                self.scraper_statuses[name] = "done"
            self.scrapers_completed += 1
            self.results_found += event.get("results_found", 0)

        elif etype == EventType.SCRAPER_FAILED:
            name = event.get("scraper_name", "")
            if name:
                self.scraper_statuses[name] = "failed"
            self.scrapers_failed += 1

        elif etype == EventType.DEDUP_RUNNING:
            if self.current_phase != Phase.DEDUPLICATING:
                self.current_phase = Phase.DEDUPLICATING
                self.phase_start_time = datetime.utcnow()
            self._dedup_processed = event.get("records_processed", self._dedup_processed)
            self._dedup_total = event.get("total_records", self._dedup_total)

        elif etype == EventType.ENRICHMENT_RUNNING:
            if self.current_phase != Phase.ENRICHING:
                self.current_phase = Phase.ENRICHING
                self.phase_start_time = datetime.utcnow()
            self._enrich_completed = event.get("records_processed", self._enrich_completed)
            self._enrich_total = event.get("total_records", self._enrich_total)

        elif etype == EventType.SEARCH_COMPLETE:
            self.current_phase = Phase.COMPLETE
            self.results_found = event.get("results_found", self.results_found)

        return self.to_state()

    # ------------------------------------------------------------------
    def to_state(self) -> ProgressState:
        phase = self.current_phase

        if phase == Phase.COLLECTING:
            pct = self.calc.collection_pct(self.scrapers_completed, self.scrapers_failed)
        elif phase == Phase.DEDUPLICATING:
            pct = self.calc.dedup_pct(self._dedup_processed, self._dedup_total)
        elif phase == Phase.ENRICHING:
            pct = self.calc.enrichment_pct(self._enrich_completed, self._enrich_total)
        elif phase == Phase.COMPLETE:
            pct = 100.0
        else:
            pct = 95.0  # finalizing

        eta = self.calc.estimate_remaining(pct, self.phase_start_time, phase)
        elapsed = (datetime.utcnow() - self.start_time).total_seconds()
        running = sum(1 for s in self.scraper_statuses.values() if s == "running")

        return ProgressState(
            search_id=self.search_id,
            current_phase=phase,
            progress_pct=round(pct, 1),
            results_found=self.results_found,
            scrapers_total=self.calc.scraper_count,
            scrapers_completed=self.scrapers_completed,
            scrapers_failed=self.scrapers_failed,
            scrapers_running=running,
            estimated_seconds_remaining=round(eta, 1),
            elapsed_seconds=round(elapsed, 1),
            scraper_statuses=dict(self.scraper_statuses),
            last_update=datetime.utcnow(),
        )
