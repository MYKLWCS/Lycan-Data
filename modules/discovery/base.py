"""Base class for all open-discovery tools."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class DiscoveryHit:
    """A single candidate URL/source returned by a discovery tool."""

    name: str
    url: str
    discovered_by: str
    discovery_query: str = ""
    category: str | None = None
    data_quality_estimate: float = 0.5
    legal_risk: str = "unknown"
    data_types: list[str] = field(default_factory=list)
    proposed_pattern: dict = field(default_factory=dict)
    raw_context: dict = field(default_factory=dict)


class BaseDiscoveryTool(ABC):
    """
    Abstract base for a single open-discovery tool.

    Each subclass wraps one external OSINT tool or API and returns
    a list of DiscoveryHit objects.
    """

    tool_name: str = "unknown"
    timeout: int = 120  # seconds

    @abstractmethod
    async def run(self, query: str) -> list[DiscoveryHit]:
        """Run the tool against *query* and return hits."""

    async def _exec(self, args: list[str], *, timeout: int | None = None) -> tuple[str, str]:
        """
        Run an external binary with a fixed arg list (no shell expansion).

        Uses asyncio.create_subprocess_exec — no shell injection surface.
        Returns (stdout, stderr). Never raises.
        """
        t = timeout or self.timeout
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=t)
            return stdout_b.decode(errors="replace"), stderr_b.decode(errors="replace")
        except TimeoutError:
            logger.warning("%s timed out after %ds", self.tool_name, t)
            return "", f"timeout after {t}s"
        except FileNotFoundError:
            logger.debug("%s binary not found: %s", self.tool_name, args[0])
            return "", "binary not found"
        except Exception as exc:
            logger.warning("%s exec error: %s", self.tool_name, exc)
            return "", str(exc)
