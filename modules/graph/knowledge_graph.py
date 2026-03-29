"""
Knowledge Graph Builder — Apache AGE backed graph for OSINT entity mapping.

Uses Cypher queries through AGE's SQL wrapper to manage the osint_graph.
All operations go through the shared asyncpg-based SQLAlchemy engine,
executing raw SQL for AGE compatibility.

SECURITY: All Cypher queries use AGE parameterized queries ($param syntax)
for user-supplied values. Labels are validated against whitelists (they
cannot be parameterized in Cypher). Entity IDs are validated as hex-only,
and search terms are sanitized to alphanumeric + safe chars.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import timezone, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Valid node labels in the osint_graph
VERTEX_LABELS = frozenset({
    "Person", "Company", "Address", "Phone", "Email",
    "Property", "Vehicle", "Court_Case", "Social_Profile",
    "Domain", "Crypto_Wallet",
})

# Valid edge labels
EDGE_LABELS = frozenset({
    "OFFICER_OF", "DIRECTOR_OF", "OWNS", "SHAREHOLDER_OF",
    "RELATIVE_OF", "ASSOCIATE_OF", "SPOUSE_OF",
    "LIVES_AT", "LOCATED_AT", "REGISTERED_AT",
    "HAS_PHONE", "HAS_EMAIL", "HAS_DOMAIN",
    "OWNS_PROPERTY", "OWNS_VEHICLE", "OWNS_WALLET",
    "PARTY_TO", "FILED_AGAINST",
    "HAS_PROFILE", "EMPLOYED_BY", "SUBSIDIARY_OF",
    "LINKED_TO",
})

_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Entity IDs are 24-char hex strings from SHA-256
_SAFE_ENTITY_ID = re.compile(r"^[0-9a-f]{24}$")

# Search terms: alphanumeric, spaces, hyphens, periods, apostrophes only
_SAFE_SEARCH = re.compile(r"^[a-zA-Z0-9 .\-']+$")


def _validate_label(label: str, allowed: frozenset[str]) -> str:
    if label not in allowed:
        raise ValueError(f"Invalid label: {label!r}")
    return label


def _validate_entity_id(eid: str) -> str:
    """Validate that entity_id is a safe hex string (output of _entity_id)."""
    if not _SAFE_ENTITY_ID.match(eid):
        raise ValueError(f"Invalid entity_id format: {eid!r}")
    return eid


def _sanitize_search_term(term: str) -> str:
    """Strip search term to alphanumeric + safe chars only."""
    sanitized = re.sub(r"[^a-zA-Z0-9 .\-']", "", term)
    if not sanitized:
        raise ValueError("Search term contains no valid characters after sanitization")
    return sanitized


def _props_literal(props: dict[str, Any]) -> str:
    """Build a Cypher property map literal from a dict, escaping values."""
    if not props:
        return ""
    parts = []
    for k, v in props.items():
        if not _SAFE_IDENT.match(k):
            continue
        if v is None:
            continue
        if isinstance(v, bool):
            parts.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            parts.append(f"{k}: {v}")
        elif isinstance(v, (list, dict)):
            escaped = json.dumps(v).replace("'", "\\'")
            parts.append(f"{k}: '{escaped}'")
        else:
            escaped = str(v).replace("\\", "\\\\").replace("'", "\\'")
            parts.append(f"{k}: '{escaped}'")
    return ", ".join(parts)


def _entity_id(label: str, identifier: str) -> str:
    """Deterministic entity ID: label + normalized identifier hash."""
    norm = identifier.strip().lower()
    return hashlib.sha256(f"{label}:{norm}".encode()).hexdigest()[:24]


def _parse_agtype_rows(rows) -> list[dict]:
    """Parse AGE agtype result rows into Python dicts."""
    parsed = []
    for row in rows:
        val = row[0]
        if isinstance(val, str):
            try:
                parsed.append(json.loads(val))
            except (json.JSONDecodeError, TypeError):
                parsed.append({"raw": val})
        elif isinstance(val, dict):
            parsed.append(val)
        else:
            parsed.append({"raw": str(val)})
    return parsed


async def _cypher(
    session: AsyncSession, query: str, params: dict[str, Any] | None = None
) -> list[dict]:
    """Execute a Cypher query via AGE SQL wrapper and return rows as dicts.

    Uses parameterized queries to prevent Cypher injection. Variable values
    should use $param_name placeholders in the Cypher query, with actual
    values passed via the params dict. Labels and relationship types must
    come from validated whitelists only (they cannot be parameterized).
    """
    if params:
        sql = text(
            "SELECT * FROM ag_catalog.cypher('osint_graph', "
            "$cypher$" + query + "$cypher$, "
            ":params::ag_catalog.agtype) AS (result ag_catalog.agtype)"
        )
        result = await session.execute(sql, {"params": json.dumps(params)})
    else:
        sql = text(
            "SELECT * FROM ag_catalog.cypher('osint_graph', "
            "$cypher$" + query + "$cypher$) AS (result ag_catalog.agtype)"
        )
        result = await session.execute(sql)
    return _parse_agtype_rows(result.fetchall())


async def _cypher_void(
    session: AsyncSession, query: str, params: dict[str, Any] | None = None
) -> None:
    """Execute a Cypher query that returns no useful data."""
    if params:
        sql = text(
            "SELECT * FROM ag_catalog.cypher('osint_graph', "
            "$cypher$" + query + "$cypher$, "
            ":params::ag_catalog.agtype) AS (result ag_catalog.agtype)"
        )
        await session.execute(sql, {"params": json.dumps(params)})
    else:
        sql = text(
            "SELECT * FROM ag_catalog.cypher('osint_graph', "
            "$cypher$" + query + "$cypher$) AS (result ag_catalog.agtype)"
        )
        await session.execute(sql)


class KnowledgeGraphBuilder:
    """
    Builds and queries the OSINT knowledge graph stored in Apache AGE.

    All methods accept an AsyncSession from the shared db layer.
    """

    # -- Entity CRUD -----------------------------------------------------------

    async def add_entity(
        self,
        label: str,
        entity_id: str,
        properties: dict[str, Any],
        session: AsyncSession,
    ) -> str:
        """
        MERGE a vertex with the given label and id.

        Returns the entity_id used (auto-generated if not provided).
        """
        _validate_label(label, VERTEX_LABELS)
        eid = entity_id or _entity_id(label, json.dumps(properties, sort_keys=True))
        eid = _validate_entity_id(eid)
        props = {**properties, "entity_id": eid, "updated_at": datetime.now(timezone.utc).isoformat()}
        query = f"MERGE (n:{label} {{entity_id: $eid}}) SET n += $props RETURN n"
        try:
            await _cypher(session, query, {"eid": eid, "props": props})
        except Exception:
            logger.exception("add_entity failed label=%s id=%s", label, eid)
            raise
        return eid

    async def get_entity(
        self,
        label: str,
        entity_id: str,
        session: AsyncSession,
    ) -> dict | None:
        """Fetch a single entity by label and entity_id."""
        _validate_label(label, VERTEX_LABELS)
        eid = _validate_entity_id(entity_id)
        query = f"MATCH (n:{label} {{entity_id: $eid}}) RETURN n"
        rows = await _cypher(session, query, {"eid": eid})
        return rows[0] if rows else None

    async def delete_entity(
        self,
        label: str,
        entity_id: str,
        session: AsyncSession,
    ) -> None:
        """Delete a vertex and all its edges."""
        _validate_label(label, VERTEX_LABELS)
        eid = _validate_entity_id(entity_id)
        query = f"MATCH (n:{label} {{entity_id: $eid}}) DETACH DELETE n"
        await _cypher_void(session, query, {"eid": eid})

    # -- Relationship CRUD -----------------------------------------------------

    async def add_relationship(
        self,
        from_label: str,
        from_id: str,
        rel_type: str,
        to_label: str,
        to_id: str,
        properties: dict[str, Any] | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        """
        MERGE an edge between two existing vertices.

        Both vertices must already exist; this will not create stubs.
        """
        _validate_label(from_label, VERTEX_LABELS)
        _validate_label(to_label, VERTEX_LABELS)
        _validate_label(rel_type, EDGE_LABELS)
        fid = _validate_entity_id(from_id)
        tid = _validate_entity_id(to_id)

        props = {**(properties or {}), "updated_at": datetime.now(timezone.utc).isoformat()}

        query = (
            f"MATCH (a:{from_label} {{entity_id: $fid}}), "
            f"(b:{to_label} {{entity_id: $tid}}) "
            f"MERGE (a)-[r:{rel_type}]->(b) "
            f"SET r += $props "
            f"RETURN r"
        )
        try:
            await _cypher(session, query, {"fid": fid, "tid": tid, "props": props})
        except Exception:
            logger.exception(
                "add_relationship failed %s->%s->%s", from_label, rel_type, to_label
            )
            raise

    async def remove_relationship(
        self,
        from_label: str,
        from_id: str,
        rel_type: str,
        to_label: str,
        to_id: str,
        session: AsyncSession | None = None,
    ) -> None:
        """Delete a specific edge between two vertices."""
        _validate_label(from_label, VERTEX_LABELS)
        _validate_label(to_label, VERTEX_LABELS)
        _validate_label(rel_type, EDGE_LABELS)
        fid = _validate_entity_id(from_id)
        tid = _validate_entity_id(to_id)

        query = (
            f"MATCH (a:{from_label} {{entity_id: $fid}})"
            f"-[r:{rel_type}]->"
            f"(b:{to_label} {{entity_id: $tid}}) "
            f"DELETE r"
        )
        await _cypher_void(session, query, {"fid": fid, "tid": tid})

    # -- Graph queries ---------------------------------------------------------

    async def find_connections(
        self,
        entity_id: str,
        max_depth: int = 3,
        session: AsyncSession | None = None,
    ) -> dict:
        """
        BFS outward from entity_id up to max_depth hops.

        Returns {nodes: [...], edges: [...]}.
        """
        eid = _validate_entity_id(entity_id)
        if max_depth < 1:
            max_depth = 1
        if max_depth > 6:
            max_depth = 6

        # Step 1: get the centre node
        centre_query = "MATCH (n {entity_id: $eid}) RETURN n"
        centre = await _cypher(session, centre_query, {"eid": eid})
        if not centre:
            return {"nodes": [], "edges": []}

        # Step 2: variable-length path expansion (max_depth is int-clamped above)
        query = (
            f"MATCH (start {{entity_id: $eid}})-[r*1..{max_depth}]-(connected) "
            f"RETURN connected"
        )
        rows = await _cypher(session, query, {"eid": eid})

        # Deduplicate
        node_map: dict[str, dict] = {}
        if centre:
            cdata = centre[0] if isinstance(centre[0], dict) else {}
            node_eid = cdata.get("entity_id", eid)
            node_map[node_eid] = cdata

        for row in rows:
            if isinstance(row, dict):
                nid = row.get("entity_id", "")
                if nid and nid not in node_map:
                    node_map[nid] = row

        return {"nodes": list(node_map.values()), "edges": []}

    async def build_company_graph(
        self,
        company_id: str,
        max_depth: int = 3,
        session: AsyncSession | None = None,
    ) -> dict:
        """
        Build a full network graph for a company: officers, directors, subsidiaries,
        addresses, domains.

        Returns {nodes, edges, node_count, edge_count}.
        """
        cid = _validate_entity_id(company_id)
        if max_depth > 5:
            max_depth = 5

        nodes: list[dict] = []
        edges: list[dict] = []
        visited: set[str] = set()

        async def _traverse(eid: str, label: str, depth: int) -> None:
            if eid in visited or depth > max_depth:
                return
            visited.add(eid)

            entity = await self.get_entity(label, eid, session)
            if not entity:
                return
            nodes.append({"id": eid, "label": label, "data": entity})

            # Fetch direct neighbours via 1-hop (eid already validated)
            neighbour_query = "MATCH (a {entity_id: $eid})-[r]-(b) RETURN b"
            neighbours = await _cypher(session, neighbour_query, {"eid": eid})
            for nb in neighbours:
                if not isinstance(nb, dict):
                    continue
                nb_id = nb.get("entity_id", "")
                if nb_id and nb_id not in visited:
                    # Validate the neighbour ID from the graph (should be hex)
                    try:
                        _validate_entity_id(nb_id)
                    except ValueError:
                        continue
                    edges.append({"source": eid, "target": nb_id})
                    nb_label = _infer_label(nb)
                    await _traverse(nb_id, nb_label, depth + 1)

        await _traverse(cid, "Company", 0)
        return {
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

    async def detect_patterns(
        self,
        pattern_type: str,
        session: AsyncSession | None = None,
    ) -> list[dict]:
        """
        Run pre-built pattern detection queries.

        Supported pattern_type values:
          - circular_ownership
          - shell_company
          - shared_officers
          - co_located_companies
        """
        # These are static queries with no user input — safe as-is
        queries = {
            "circular_ownership": (
                "MATCH (c1:Company)-[:OWNS*2..4]->(c2:Company)-[:OWNS*1..]->(c1) "
                "RETURN c1, c2"
            ),
            "shell_company": (
                "MATCH (c1:Company)-[:LOCATED_AT]->(a:Address)<-[:LOCATED_AT]-(c2:Company) "
                "RETURN c1, c2, a"
            ),
            "shared_officers": (
                "MATCH (c1:Company)<-[:OFFICER_OF]-(p:Person)-[:OFFICER_OF]->(c2:Company) "
                "RETURN p, c1, c2"
            ),
            "co_located_companies": (
                "MATCH (c1:Company)-[:LOCATED_AT]->(a:Address)<-[:LOCATED_AT]-(c2:Company) "
                "RETURN c1, c2, a"
            ),
        }
        if pattern_type not in queries:
            raise ValueError(f"Unknown pattern_type: {pattern_type!r}")

        return await _cypher(session, queries[pattern_type])

    # -- Expanding search (UI-oriented) ----------------------------------------

    async def expand_node(
        self,
        entity_id: str,
        session: AsyncSession | None = None,
    ) -> dict:
        """
        1-hop expansion from a single node. Used by the expanding search UI
        when a user clicks a node to see its neighbours.

        Returns {centre, neighbours: [{node, edge_type}]}.
        """
        eid = _validate_entity_id(entity_id)
        centre_query = "MATCH (n {entity_id: $eid}) RETURN n"
        centre_rows = await _cypher(session, centre_query, {"eid": eid})
        centre = centre_rows[0] if centre_rows else None

        neighbour_query = "MATCH (a {entity_id: $eid})-[r]-(b) RETURN b"
        neighbours = await _cypher(session, neighbour_query, {"eid": eid})

        return {
            "centre": centre,
            "neighbours": [
                {"node": nb, "edge_type": "connected"}
                for nb in neighbours
                if isinstance(nb, dict)
            ],
        }

    async def search_entities(
        self,
        label: str,
        search_term: str,
        limit: int = 20,
        session: AsyncSession | None = None,
    ) -> list[dict]:
        """
        Search entities by label and a property substring (name, legal_name, etc.).
        """
        _validate_label(label, VERTEX_LABELS)
        sanitized = _sanitize_search_term(search_term).lower()
        # Escape regex special chars for Cypher =~ operator
        escaped = re.sub(r"([.*+?^${}()|\\[\]])", r"\\\1", sanitized)
        pattern = f"(?i).*{escaped}.*"

        name_field = "legal_name" if label == "Company" else "name"
        safe_limit = min(max(1, limit), 100)
        query = (
            f"MATCH (n:{label}) "
            f"WHERE n.{name_field} =~ $pattern "
            f"RETURN n "
            f"LIMIT {safe_limit}"
        )
        return await _cypher(session, query, {"pattern": pattern})

    # -- Graph statistics ------------------------------------------------------

    async def graph_stats(self, session: AsyncSession) -> dict:
        """Return vertex/edge counts per label."""
        counts: dict[str, int] = {}
        for label in VERTEX_LABELS:
            # Labels are from VERTEX_LABELS frozenset — no user input
            query = f"MATCH (n:{label}) RETURN count(n)"
            rows = await _cypher(session, query)
            counts[label] = rows[0] if rows and isinstance(rows[0], (int, float)) else 0

        return {"vertex_counts": counts}


def _infer_label(props: dict) -> str:
    """Best-effort label inference from AGE vertex properties."""
    if "legal_name" in props or "ein" in props:
        return "Company"
    if "full_name" in props or "dob" in props:
        return "Person"
    if "street" in props or "zip" in props:
        return "Address"
    if "number" in props and "carrier" in props:
        return "Phone"
    if "address" in props and "domain" in props and "breach_count" in props:
        return "Email"
    if "vin" in props:
        return "Vehicle"
    if "case_number" in props:
        return "Court_Case"
    if "platform" in props and "username" in props:
        return "Social_Profile"
    if "domain_name" in props:
        return "Domain"
    if "chain" in props and "balance" in props:
        return "Crypto_Wallet"
    if "value" in props and "tax_assessment" in props:
        return "Property"
    return "Person"
