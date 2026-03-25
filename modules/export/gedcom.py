"""
gedcom.py — GEDCOM 5.5.5 export from FamilyTreeSnapshot.tree_json.
"""

from __future__ import annotations

_MONTHS = {
    "01": "JAN", "02": "FEB", "03": "MAR", "04": "APR",
    "05": "MAY", "06": "JUN", "07": "JUL", "08": "AUG",
    "09": "SEP", "10": "OCT", "11": "NOV", "12": "DEC",
}


def _format_gedcom_date(date_str: str) -> str:
    """Convert ISO date (YYYY-MM-DD or YYYY) to GEDCOM date format (DD MON YYYY)."""
    if not date_str:
        return ""
    parts = date_str.split("-")
    if len(parts) == 3:
        y, m, d = parts
        mon = _MONTHS.get(m, m)
        return f"{d} {mon} {y}"
    if len(parts) == 1 and len(date_str) == 4:
        return date_str
    return date_str


def generate_gedcom(tree_json: dict, root_person_id: str) -> str:
    """Generate a GEDCOM 5.5.5 format string from tree JSON."""
    lines: list[str] = [
        "0 HEAD",
        "1 SOUR Lycan",
        "2 VERS 1.0",
        "2 NAME Lycan OSINT Platform",
        "1 GEDC",
        "2 VERS 5.5.5",
        "1 CHAR UTF-8",
        "1 SUBM @SUBM1@",
        "0 @SUBM1@ SUBM",
        "1 NAME Lycan Platform",
    ]

    nodes: dict[str, dict] = tree_json.get("nodes", {})
    edges: list[dict] = tree_json.get("edges", [])

    node_ids = list(nodes.keys())
    indi_map: dict[str, str] = {uid: f"@I{i + 1}@" for i, uid in enumerate(node_ids)}

    for uid, node in nodes.items():
        gedcom_id = indi_map[uid]
        lines.append(f"0 {gedcom_id} INDI")
        name = node.get("name") or node.get("full_name") or "Unknown"
        parts = name.rsplit(" ", 1)
        if len(parts) == 2:
            gedcom_name = f"{parts[0]} /{parts[1]}/"
        else:
            gedcom_name = f"/{name}/"
        lines.append(f"1 NAME {gedcom_name}")
        birth_date = node.get("birth_date")
        if birth_date:
            lines.append("1 BIRT")
            lines.append(f"2 DATE {_format_gedcom_date(birth_date)}")
        death_date = node.get("death_date")
        if death_date:
            lines.append("1 DEAT")
            lines.append(f"2 DATE {_format_gedcom_date(death_date)}")

    fam_counter = 0
    processed_couples: set = set()

    for edge in edges:
        if edge.get("rel_type") != "spouse_of":
            continue
        from_id = str(edge.get("from") or edge.get("person_a_id") or "")
        to_id = str(edge.get("to") or edge.get("person_b_id") or "")
        if not from_id or not to_id:
            continue
        pair = frozenset([from_id, to_id])
        if pair in processed_couples:
            continue
        processed_couples.add(pair)
        fam_counter += 1
        fam_id = f"@F{fam_counter}@"
        husb_id = indi_map.get(from_id)
        wife_id = indi_map.get(to_id)
        if not husb_id or not wife_id:
            continue
        lines.append(f"0 {fam_id} FAM")
        lines.append(f"1 HUSB {husb_id}")
        lines.append(f"1 WIFE {wife_id}")

    lines.append("0 TRLR")
    return "\n".join(lines)
