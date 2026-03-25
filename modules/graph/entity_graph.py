"""
Entity Graph Builder — constructs relationship graphs from the Lycan-Data store.

Covers:
  - Person-centred graphs up to N hops
  - Shared connection detection across a list of persons
  - Fraud ring detection via shared addresses / phone numbers
"""

from __future__ import annotations

import uuid
from collections import defaultdict, deque

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.address import Address
from shared.models.employment import EmploymentHistory
from shared.models.identifier import Identifier
from shared.models.person import Person
from shared.models.relationship import Relationship
from shared.models.social_profile import SocialProfile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _person_node(person: Person) -> dict:
    return {
        "id": str(person.id),
        "type": "person",
        "label": person.full_name or str(person.id),
        "risk_score": person.default_risk_score or 0.0,
    }


def _stub_node(node_id: str, node_type: str, label: str) -> dict:
    return {"id": node_id, "type": node_type, "label": label, "risk_score": 0.0}


def _edge(source: str, target: str, edge_type: str, confidence: float) -> dict:
    return {"source": source, "target": target, "type": edge_type, "confidence": confidence}


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class EntityGraphBuilder:
    """Build entity-relationship graphs from the Lycan-Data relational store."""

    async def build_person_graph(
        self,
        person_id: str,
        session: AsyncSession,
        depth: int = 2,
    ) -> dict:
        """
        Build a relationship graph centred on `person_id` up to `depth` hops.

        Node types : person, company, address, phone, email
        Edge types : relationship, employment, lives_at, has_phone, has_email,
                     has_social
        """
        root_uuid = uuid.UUID(person_id)

        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        visited_persons: set[uuid.UUID] = set()
        frontier: set[uuid.UUID] = {root_uuid}

        for _hop in range(depth):
            if not frontier:
                break
            next_frontier: set[uuid.UUID] = set()

            # Fetch person records for the current frontier
            p_stmt = select(Person).where(Person.id.in_(list(frontier)))
            p_result = await session.execute(p_stmt)
            person_rows: list[Person] = list(p_result.scalars().all())

            for person in person_rows:
                pid = person.id
                pid_str = str(pid)
                if pid in visited_persons:  # pragma: no cover
                    continue
                visited_persons.add(pid)
                nodes[pid_str] = _person_node(person)

            # Batch all associated data for the entire frontier at once
            frontier_list = list(frontier)

            addr_rows_batch = (
                (await session.execute(select(Address).where(Address.person_id.in_(frontier_list))))
                .scalars()
                .all()
            )
            addr_by_pid: dict[uuid.UUID, list] = defaultdict(list)
            for a in addr_rows_batch:
                addr_by_pid[a.person_id].append(a)

            ident_rows_batch = (
                (
                    await session.execute(
                        select(Identifier).where(Identifier.person_id.in_(frontier_list))
                    )
                )
                .scalars()
                .all()
            )
            ident_by_pid: dict[uuid.UUID, list] = defaultdict(list)
            for i in ident_rows_batch:
                ident_by_pid[i.person_id].append(i)

            emp_rows_batch = (
                (
                    await session.execute(
                        select(EmploymentHistory).where(
                            EmploymentHistory.person_id.in_(frontier_list),
                            EmploymentHistory.employer_name.isnot(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            emp_by_pid: dict[uuid.UUID, list] = defaultdict(list)
            for e in emp_rows_batch:
                emp_by_pid[e.person_id].append(e)

            sp_rows_batch = (
                (
                    await session.execute(
                        select(SocialProfile).where(SocialProfile.person_id.in_(frontier_list))
                    )
                )
                .scalars()
                .all()
            )
            sp_by_pid: dict[uuid.UUID, list] = defaultdict(list)
            for s in sp_rows_batch:
                sp_by_pid[s.person_id].append(s)

            rel_rows_batch = (
                (
                    await session.execute(
                        select(Relationship).where(
                            (Relationship.person_a_id.in_(frontier_list))
                            | (Relationship.person_b_id.in_(frontier_list))
                        )
                    )
                )
                .scalars()
                .all()
            )
            rel_by_pid: dict[uuid.UUID, list] = defaultdict(list)
            for r in rel_rows_batch:
                rel_by_pid[r.person_a_id].append(r)
                rel_by_pid[r.person_b_id].append(r)

            edge_keys: set[frozenset] = set()

            def _add_edge_dedup(source: str, target: str, etype: str, conf: float) -> None:
                key = frozenset([source, target, etype])
                if key not in edge_keys:
                    edge_keys.add(key)
                    edges.append(_edge(source, target, etype, conf))

            for person in person_rows:
                pid = person.id
                pid_str = str(pid)

                # --- Addresses ---
                for addr in addr_by_pid.get(pid, []):
                    addr_id = f"addr:{addr.id}"
                    label = ", ".join(
                        filter(None, [addr.street, addr.city, addr.state_province])
                    ) or str(addr.id)
                    nodes[addr_id] = _stub_node(addr_id, "address", label)
                    edges.append(_edge(pid_str, addr_id, "lives_at", 0.95))

                # --- Identifiers ---
                for ident in ident_by_pid.get(pid, []):
                    itype = ident.type.lower()
                    if itype not in ("phone", "email", "ssn", "passport"):
                        continue
                    node_type = itype if itype in ("phone", "email") else "identifier"
                    edge_type = f"has_{itype}"
                    iid = f"ident:{ident.id}"
                    nodes[iid] = _stub_node(iid, node_type, ident.value)
                    edges.append(_edge(pid_str, iid, edge_type, ident.confidence or 1.0))

                # --- Employment / company nodes ---
                for emp in emp_by_pid.get(pid, []):
                    emp_name = emp.employer_name or ""
                    cid = f"company:{uuid.uuid5(uuid.NAMESPACE_DNS, emp_name.lower().strip())}"
                    if cid not in nodes:
                        nodes[cid] = _stub_node(cid, "company", emp_name)
                    edge_type = "officer" if emp.job_title else "employee"
                    conf = 0.9 if emp.is_current else 0.6
                    edges.append(_edge(pid_str, cid, edge_type, conf))

                # --- Social profiles ---
                for sp in sp_by_pid.get(pid, []):
                    sp_id = f"social:{sp.id}"
                    label = f"{sp.platform}:{sp.handle or sp.platform_user_id}"
                    nodes[sp_id] = _stub_node(sp_id, "social_profile", label)
                    edges.append(_edge(pid_str, sp_id, "has_social", 1.0))

                # --- Relationships → expand frontier (deduplicated) ---
                seen_rels: set[uuid.UUID] = set()
                for rel in rel_by_pid.get(pid, []):
                    if rel.id in seen_rels:
                        continue
                    seen_rels.add(rel.id)
                    other_id = rel.person_b_id if rel.person_a_id == pid else rel.person_a_id
                    other_str = str(other_id)
                    if other_id not in visited_persons:
                        next_frontier.add(other_id)
                        if other_str not in nodes:
                            nodes[other_str] = _stub_node(other_str, "person", other_str)
                    _add_edge_dedup(pid_str, other_str, rel.rel_type, rel.score or 0.5)

            frontier = next_frontier - visited_persons

        return {"nodes": list(nodes.values()), "edges": edges}

    async def find_shared_connections(
        self,
        person_ids: list[str],
        session: AsyncSession,
    ) -> list[dict]:
        """
        Find identifiers, addresses, and employers shared across the given persons.

        Returns a list of:
          {type, value, person_ids: [...], risk_implication}
        """
        if len(person_ids) < 2:
            return []

        pid_uuids = [uuid.UUID(p) for p in person_ids]
        shared: list[dict] = []

        # --- Shared identifiers (phone, email) ---
        id_stmt = select(Identifier).where(
            Identifier.person_id.in_(pid_uuids),
            Identifier.type.in_(["phone", "email"]),
        )
        id_result = await session.execute(id_stmt)
        ident_rows: list[Identifier] = list(id_result.scalars().all())

        value_map: dict[tuple[str, str], set[str]] = defaultdict(set)
        for row in ident_rows:
            key = (row.type, (row.normalized_value or row.value).lower().strip())
            if row.person_id:
                value_map[key].add(str(row.person_id))

        for (itype, value), pids in value_map.items():
            if len(pids) > 1:
                shared.append(
                    {
                        "type": itype,
                        "value": value,
                        "person_ids": list(pids),
                        "risk_implication": "shared_identifier",
                    }
                )

        # --- Shared addresses ---
        addr_stmt = select(Address).where(Address.person_id.in_(pid_uuids))
        addr_result = await session.execute(addr_stmt)
        addr_rows: list[Address] = list(addr_result.scalars().all())

        addr_map: dict[str, list[str]] = defaultdict(list)
        for row in addr_rows:
            if row.street and row.city:
                key = f"{row.street.lower().strip()}|{row.city.lower().strip()}"
                if row.person_id:
                    addr_map[key].append(str(row.person_id))

        for addr_key, pids in addr_map.items():
            if len(pids) > 1:
                street, city = addr_key.split("|", 1)
                shared.append(
                    {
                        "type": "address",
                        "value": f"{street}, {city}",
                        "person_ids": pids,
                        "risk_implication": "shared_address",
                    }
                )

        # --- Shared employers ---
        emp_stmt = select(EmploymentHistory).where(
            EmploymentHistory.person_id.in_(pid_uuids),
            EmploymentHistory.employer_name.isnot(None),
        )
        emp_result = await session.execute(emp_stmt)
        emp_rows: list[EmploymentHistory] = list(emp_result.scalars().all())

        emp_map: dict[str, list[str]] = defaultdict(list)
        for row in emp_rows:
            key = (row.employer_name or "").lower().strip()
            if row.person_id:
                emp_map[key].append(str(row.person_id))

        for emp_name, pids in emp_map.items():
            if len(pids) > 1:
                shared.append(
                    {
                        "type": "employer",
                        "value": emp_name,
                        "person_ids": pids,
                        "risk_implication": "shared_employer",
                    }
                )

        return shared

    async def detect_fraud_rings(
        self,
        session: AsyncSession,
        min_connections: int = 3,
    ) -> list[dict]:
        """
        Find clusters of persons sharing the same address or phone number.

        Returns a list of:
          {persons: [...], shared_element: str, risk_score: float}
        """
        rings: list[dict] = []

        # --- Address-based clusters ---
        addr_stmt = select(Address).where(
            Address.street.isnot(None),
            Address.city.isnot(None),
            Address.person_id.isnot(None),
        )
        addr_result = await session.execute(addr_stmt)
        addr_rows: list[Address] = list(addr_result.scalars().all())

        addr_cluster: dict[str, list[str]] = defaultdict(list)
        for row in addr_rows:
            key = f"{(row.street or '').lower().strip()}|{(row.city or '').lower().strip()}"
            addr_cluster[key].append(str(row.person_id))

        for addr_key, person_ids in addr_cluster.items():
            unique_persons = list(set(person_ids))
            if len(unique_persons) >= min_connections:
                street, city = addr_key.split("|", 1)
                n = len(unique_persons)
                risk = min(0.4 + 0.1 * (n - min_connections), 1.0)
                rings.append(
                    {
                        "persons": unique_persons,
                        "shared_element": f"address:{street}, {city}",
                        "risk_score": round(risk, 3),
                    }
                )

        # --- Phone-based clusters ---
        phone_stmt = select(Identifier).where(
            Identifier.type == "phone",
            Identifier.person_id.isnot(None),
        )
        phone_result = await session.execute(phone_stmt)
        phone_rows: list[Identifier] = list(phone_result.scalars().all())

        phone_cluster: dict[str, list[str]] = defaultdict(list)
        for row in phone_rows:
            key = (row.normalized_value or row.value).lower().strip()
            phone_cluster[key].append(str(row.person_id))

        for phone_val, person_ids in phone_cluster.items():
            unique_persons = list(set(person_ids))
            if len(unique_persons) >= min_connections:
                n = len(unique_persons)
                risk = min(0.5 + 0.1 * (n - min_connections), 1.0)
                rings.append(
                    {
                        "persons": unique_persons,
                        "shared_element": f"phone:{phone_val}",
                        "risk_score": round(risk, 3),
                    }
                )

        # Sort by risk descending
        rings.sort(key=lambda r: r["risk_score"], reverse=True)
        return rings

    # ── Phase 3 methods ───────────────────────────────────────────────────────

    async def get_nodes_paginated(
        self,
        session: AsyncSession,
        limit: int = 500,
        offset: int = 0,
        entity_types: list[str] | None = None,
    ) -> list[dict]:
        """
        Return a flat page of graph nodes ordered by degree (risk_score desc as proxy).
        Supported entity_types: person, company, address, phone, email.
        When entity_types is None or empty, persons are returned (most-connected first).
        """
        from shared.models.address import Address
        from shared.models.employment import EmploymentHistory
        from shared.models.identifier import Identifier

        allowed = entity_types or ["person"]
        nodes: list[dict] = []

        if "person" in allowed:
            stmt = (
                select(Person)
                .order_by(Person.default_risk_score.desc())
                .limit(limit)
                .offset(offset)
            )
            rows = (await session.execute(stmt)).scalars().all()
            for p in rows:
                nodes.append(_person_node(p))

        if "address" in allowed:
            stmt = select(Address).limit(limit).offset(offset)
            rows = (await session.execute(stmt)).scalars().all()
            for a in rows:
                label = ", ".join(filter(None, [a.street, a.city, a.state_province])) or str(a.id)
                nodes.append(_stub_node(f"addr:{a.id}", "address", label))

        if "phone" in allowed:
            stmt = (
                select(Identifier)
                .where(Identifier.type == "phone")
                .limit(limit)
                .offset(offset)
            )
            rows = (await session.execute(stmt)).scalars().all()
            for i in rows:
                nodes.append(_stub_node(f"ident:{i.id}", "phone", i.value))

        if "email" in allowed:
            stmt = (
                select(Identifier)
                .where(Identifier.type == "email")
                .limit(limit)
                .offset(offset)
            )
            rows = (await session.execute(stmt)).scalars().all()
            for i in rows:
                nodes.append(_stub_node(f"ident:{i.id}", "email", i.value))

        if "company" in allowed:
            stmt = (
                select(EmploymentHistory)
                .where(EmploymentHistory.employer_name.isnot(None))
                .distinct(EmploymentHistory.employer_name)
                .limit(limit)
                .offset(offset)
            )
            rows = (await session.execute(stmt)).scalars().all()
            seen: set[str] = set()
            for e in rows:
                name = e.employer_name or ""
                cid = f"company:{uuid.uuid5(uuid.NAMESPACE_DNS, name.lower().strip())}"
                if cid not in seen:
                    seen.add(cid)
                    nodes.append(_stub_node(cid, "company", name))

        return nodes[:limit]

    async def get_edges_paginated(
        self,
        session: AsyncSession,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict]:
        """
        Return a paginated list of relationship edges between person nodes.
        Each edge: {source, target, type, confidence}.
        """
        stmt = select(Relationship).limit(limit).offset(offset)
        rows = (await session.execute(stmt)).scalars().all()
        return [
            _edge(
                str(r.person_a_id),
                str(r.person_b_id),
                r.rel_type,
                r.score if r.score is not None else 0.5,
            )
            for r in rows
        ]

    async def find_shortest_path(
        self,
        from_id: str,
        to_id: str,
        session: AsyncSession,
        entity_types: list[str] | None,
        max_hops: int = 6,
    ) -> dict:
        """
        BFS shortest path between two person nodes.

        entity_types: if provided, only traverse through person nodes whose UUIDs
        are present (non-person entity nodes are never traversal waypoints in the
        current schema — they are leaves). Pass None or ["person"] to traverse all.
        max_hops: maximum number of edges to traverse. Hard cap 10.

        Returns:
            {"path": [id, ...], "edges": [{source, target, type, confidence}]}
            or {"path": null, "reason": "no_path_within_max_hops"}
        """
        if max_hops > 10:
            raise ValueError(f"max_hops must be <= 10, got {max_hops}")

        # Load full relationship adjacency list
        stmt = select(Relationship)
        rows = (await session.execute(stmt)).scalars().all()

        # Build adjacency: node_id → list[(neighbour_id, rel)]
        adj: dict[str, list[tuple[str, object]]] = defaultdict(list)
        for r in rows:
            a, b = str(r.person_a_id), str(r.person_b_id)
            adj[a].append((b, r))
            adj[b].append((a, r))

        # BFS
        start, end = from_id, to_id
        if start == end:
            return {"path": [start], "edges": []}

        visited: set[str] = {start}
        # Queue items: (current_node, path_so_far, edges_so_far)
        queue: deque[tuple[str, list[str], list[dict]]] = deque()
        queue.append((start, [start], []))

        while queue:
            current, path, path_edges = queue.popleft()
            if len(path) - 1 >= max_hops:
                continue
            for neighbour, rel in adj[current]:
                if neighbour in visited:
                    continue
                new_path = path + [neighbour]
                new_edges = path_edges + [
                    _edge(current, neighbour, rel.rel_type, rel.score or 0.5)
                ]
                if neighbour == end:
                    return {"path": new_path, "edges": new_edges}
                visited.add(neighbour)
                queue.append((neighbour, new_path, new_edges))

        return {"path": None, "reason": "no_path_within_max_hops"}

    async def expand_entity(
        self,
        entity_type: str,
        entity_id: str,
        session: AsyncSession,
    ) -> dict:
        """
        Return 1-hop graph expansion for any entity type.

        For person nodes: runs build_person_graph at depth=1.
        Other entity types are not yet traversable as graph roots (stub returns
        the single node with no neighbours — raises ValueError for unknown types).
        """
        supported = {"person", "company", "address", "email", "phone", "domain", "ip", "wallet"}
        if entity_type not in supported:
            raise ValueError(f"Unsupported entity_type: {entity_type!r}")

        if entity_type == "person":
            return await self.build_person_graph(entity_id, session, depth=1)

        # Non-person entity: return the stub node only (no traversal model yet)
        return {
            "nodes": [_stub_node(f"{entity_type}:{entity_id}", entity_type, entity_id)],
            "edges": [],
        }
