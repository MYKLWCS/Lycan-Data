"""
gedcom.py — GEDCOM 5.5.5 export utility.

Converts a list of person dicts and relationship dicts into a valid
GEDCOM 5.5.5 file string suitable for import into genealogy applications.
"""


def export_gedcom(persons: list[dict], relationships: list[dict]) -> str:
    """
    Generate a GEDCOM 5.5.5 file from person and relationship data.

    Args:
        persons: list of person dicts with optional keys:
            full_name, date_of_birth, gender
        relationships: list of relationship dicts (currently unused in output
            but reserved for FAM record generation in a future pass)

    Returns:
        GEDCOM file content as a UTF-8 string.
    """
    lines = [
        "0 HEAD",
        "1 SOUR Lycan",
        "2 VERS 1.0",
        "1 GEDC",
        "2 VERS 5.5.5",
        "1 CHAR UTF-8",
    ]

    for i, p in enumerate(persons, 1):
        tag = f"@I{i}@"
        lines.append(f"0 {tag} INDI")
        if p.get("full_name"):
            parts = p["full_name"].split()
            surname = parts[-1] if len(parts) > 1 else p["full_name"]
            given = " ".join(parts[:-1]) if len(parts) > 1 else ""
            lines.append(f"1 NAME {given} /{surname}/")
        if p.get("date_of_birth"):
            lines.append("1 BIRT")
            lines.append(f"2 DATE {p['date_of_birth']}")
        if p.get("gender"):
            gender_code = "M" if p["gender"].lower().startswith("m") else "F"
            lines.append(f"1 SEX {gender_code}")

    lines.append("0 TRLR")
    return "\n".join(lines)
