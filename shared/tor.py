import asyncio
import logging
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from stem import Signal
from stem.control import Controller

from shared.config import settings

logger = logging.getLogger(__name__)


class TorInstance(Enum):
    TOR1 = "tor1"  # Social media actors
    TOR2 = "tor2"  # Scrapy spiders, enrichment
    TOR3 = "tor3"  # Dark web


@dataclass
class TorEndpoint:
    name: str
    socks_url: str
    control_host: str
    control_port: int
    controller: Any = field(default=None, repr=False)
    is_connected: bool = False


class TorManager:
    """
    Manages 3 Tor instances for anonymous outbound requests.

    Each instance is assigned a role:
    - TOR1: social media actors (Playwright)
    - TOR2: Scrapy spiders + enrichment
    - TOR3: dark web (.onion crawling)

    Usage:
        tor = TorManager()
        await tor.connect_all()
        proxy_url = tor.get_proxy(TorInstance.TOR1)
        await tor.new_circuit(TorInstance.TOR1)
        await tor.disconnect_all()
    """

    def __init__(self) -> None:
        self._endpoints: dict[TorInstance, TorEndpoint] = {
            TorInstance.TOR1: TorEndpoint(
                name="tor1",
                socks_url=settings.tor1_socks,
                control_host="127.0.0.1",
                control_port=settings.tor1_control_port,
            ),
            TorInstance.TOR2: TorEndpoint(
                name="tor2",
                socks_url=settings.tor2_socks,
                control_host="127.0.0.1",
                control_port=settings.tor2_control_port,
            ),
            TorInstance.TOR3: TorEndpoint(
                name="tor3",
                socks_url=settings.tor3_socks,
                control_host="127.0.0.1",
                control_port=settings.tor3_control_port,
            ),
        }

    def get_proxy(self, instance: TorInstance = TorInstance.TOR2) -> str:
        """Return the SOCKS5 proxy URL for this instance (or proxy_override)."""
        if settings.proxy_override:
            return settings.proxy_override
        if not settings.tor_enabled:
            return ""
        return self._endpoints[instance].socks_url

    def get_proxy_for_role(self, role: str) -> str:
        """Map role name to instance. role: 'social', 'spider', 'darkweb'."""
        mapping = {
            "social": TorInstance.TOR1,
            "spider": TorInstance.TOR2,
            "enrichment": TorInstance.TOR2,
            "darkweb": TorInstance.TOR3,
        }
        instance = mapping.get(role, TorInstance.TOR2)
        return self.get_proxy(instance)

    async def connect_all(self) -> None:
        """Attempt to connect to all Tor control ports. Failures are logged, not raised."""
        if not settings.tor_enabled:
            logger.info("Tor disabled — skipping connection")
            return
        tasks = [self._connect(inst) for inst in TorInstance]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _connect(self, instance: TorInstance) -> None:
        ep = self._endpoints[instance]
        try:
            loop = asyncio.get_running_loop()
            controller = await loop.run_in_executor(
                None,
                lambda: Controller.from_port(address=ep.control_host, port=ep.control_port),
            )
            await loop.run_in_executor(
                None,
                lambda: controller.authenticate(password=settings.tor_control_password),
            )
            ep.controller = controller
            ep.is_connected = True
            logger.info("Connected to %s control port %d", ep.name, ep.control_port)
        except Exception as exc:
            logger.warning("Could not connect to %s: %s", ep.name, exc)
            ep.is_connected = False

    async def disconnect_all(self) -> None:
        for instance, ep in self._endpoints.items():
            if ep.controller and ep.is_connected:
                try:
                    ep.controller.close()
                except Exception:
                    pass
                ep.is_connected = False
                logger.info("Disconnected from %s", ep.name)

    async def new_circuit(self, instance: TorInstance = TorInstance.TOR2) -> bool:
        """Request a new Tor circuit (new exit IP). Returns True on success."""
        if not settings.tor_enabled:
            return False
        ep = self._endpoints[instance]
        if not ep.is_connected or ep.controller is None:
            logger.warning("Cannot rotate circuit — %s not connected", ep.name)
            return False
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: ep.controller.signal(Signal.NEWNYM))
            logger.info("New circuit requested on %s", ep.name)
            return True
        except Exception as exc:
            logger.warning("Circuit rotation failed on %s: %s", ep.name, exc)
            return False

    async def new_circuit_all(self) -> None:
        """Rotate all connected instances."""
        tasks = [self.new_circuit(inst) for inst in TorInstance]
        await asyncio.gather(*tasks, return_exceptions=True)

    def is_available(self, instance: TorInstance = TorInstance.TOR2) -> bool:
        return settings.tor_enabled and self._endpoints[instance].is_connected

    def any_available(self) -> bool:
        return any(ep.is_connected for ep in self._endpoints.values())

    def status(self) -> dict[str, bool]:
        return {inst.value: ep.is_connected for inst, ep in self._endpoints.items()}


# Module-level singleton
tor_manager = TorManager()
