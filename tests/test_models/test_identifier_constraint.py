import sqlalchemy as sa

from shared.models.identifier import Identifier


def test_unique_constraint_on_normalized_value():
    table = Identifier.__table__
    constraints = {c.name for c in table.constraints if isinstance(c, sa.UniqueConstraint)}
    assert "uq_identifier_type_normalized" in constraints
    assert "uq_identifier_type_value" not in constraints


def test_normalized_value_not_nullable():
    col = Identifier.__table__.c.normalized_value
    assert col.nullable is False
