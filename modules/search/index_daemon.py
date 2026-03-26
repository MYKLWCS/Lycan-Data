"""
Index Daemon.

Listens on the 'index' queue for person_ids that need updating.
Fetches the full current state of the person from PostgreSQL —
identifiers, addresses, social profiles — then pushes the complete
document to Typesense for sub-millisecond region + full-text search.
"""

import asyncio
import json
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.search.meili_indexer import build_person_doc, meili_indexer
from shared.db import AsyncSessionLocal
from shared.events import event_bus
from shared.models.address import Address
from shared.models.identifier import Identifier
from shared.models.person import Person
from shared.models.social_profile import SocialProfile

logger = logging.getLogger(__name__)


class IndexDaemon:
    """Consumes indexing requests and updates Typesense."""

    def __init__(self, worker_id: str = "indexer-1"):
        self.worker_id = worker_id
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info(f"Index Daemon {self.worker_id} started")
        while self._running:
            try:
                await self._process_one()
            except Exception as exc:
                logger.exception(f"Index Daemon loop error: {exc}")
                await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False

    async def _process_one(self) -> None:
        raw = await event_bus.dequeue(priority="index", timeout=5)
        if raw is None:
            return

        if isinstance(raw, dict):
            payload = raw
        else:
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"Invalid index payload: {raw!r}")
                return

        pid_str = payload.get("person_id")
        if not pid_str:
            return

        try:
            uid = uuid.UUID(pid_str)
        except ValueError:
            logger.warning(f"Invalid UUID in index payload: {pid_str}")
            return

        async with AsyncSessionLocal() as session:
            try:
                await self._index_person(session, uid)
            except Exception as e:
                logger.error(f"Error preparing index for {uid}: {e}")

    async def _index_person(self, session: AsyncSession, uid: uuid.UUID) -> None:
        p = await session.get(Person, uid)
        if not p:
            logger.warning(f"Person not found for indexing: {uid}")
            return

        # Fetch all related data in parallel-ish queries
        idents = (
            (await session.execute(select(Identifier).where(Identifier.person_id == p.id)))
            .scalars()
            .all()
        )

        addresses = (
            (await session.execute(select(Address).where(Address.person_id == p.id)))
            .scalars()
            .all()
        )

        profiles = (
            (await session.execute(select(SocialProfile).where(SocialProfile.person_id == p.id)))
            .scalars()
            .all()
        )

        # Extract typed identifiers
        phones = [i.value for i in idents if i.type == "phone"]
        emails = [i.value for i in idents if i.type == "email"]
        usernames = [i.value for i in idents if i.type == "username"]

        # Extract platform names
        platforms = list({s.platform for s in profiles if s.platform})

        # Extract address data — prefer current address, fall back to any
        city = state = country = None
        addresses_text: list[str] = []

        current = [a for a in addresses if a.is_current]
        addr_list = current or list(addresses)

        for addr in addr_list[:5]:  # cap at 5 addresses
            parts = [
                p
                for p in [
                    addr.street,
                    addr.city,
                    addr.state_province,
                    addr.postal_code,
                    addr.country,
                ]
                if p
            ]
            if parts:
                addresses_text.append(", ".join(parts))

        if addr_list:
            primary = addr_list[0]
            city = primary.city
            state = primary.state_province
            country = primary.country

        # Risk tier label
        score = p.default_risk_score or 0.0
        if score >= 0.80:
            risk_tier = "do_not_lend"
        elif score >= 0.60:
            risk_tier = "high_risk"
        elif score >= 0.40:
            risk_tier = "medium_risk"
        elif score >= 0.20:
            risk_tier = "low_risk"
        else:
            risk_tier = "preferred"

        doc = build_person_doc(
            person_id=str(p.id),
            full_name=p.full_name,
            dob=p.date_of_birth.isoformat() if p.date_of_birth else None,
            phones=phones,
            emails=emails,
            usernames=usernames,
            platforms=platforms,
            addresses_text=addresses_text,
            city=city,
            state_province=state,
            country=country,
            default_risk_score=score,
            risk_tier=risk_tier,
            nationality=p.nationality,
            has_darkweb=p.darkweb_exposure > 0,
            has_addresses=bool(addresses),
            verification_status=p.verification_status,
            composite_quality=p.composite_quality,
            corroboration_count=p.corroboration_count,
            created_at=p.created_at.isoformat() if p.created_at else None,
        )

        success = await meili_indexer.index_person(doc)
        if not success:
            logger.error(f"Typesense index failed for person {uid}")
        else:
            logger.debug(f"Indexed person {uid} — city={city}, platforms={platforms}")
