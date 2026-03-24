"""Add marketing_tags, consumer_segments, ticket_sizes, audit_log, search_progress, opt_outs tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TS_COLS = [
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
]


def upgrade() -> None:
    # ── marketing_tags ────────────────────────────────────────────────────────
    op.create_table(
        'marketing_tags',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('person_id', sa.UUID(), nullable=False),
        sa.Column('tag', sa.String(length=100), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('reasoning', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('tag_category', sa.String(length=50), nullable=True),
        sa.Column('scored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('model_version', sa.String(length=20), nullable=False, server_default='1.0'),
        *_TS_COLS,
        sa.ForeignKeyConstraint(['person_id'], ['persons.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('person_id', 'tag', name='uq_marketing_tag_person_tag'),
    )
    op.create_index('ix_marketing_tag_person_tag', 'marketing_tags', ['person_id', 'tag'])

    # ── consumer_segments ─────────────────────────────────────────────────────
    op.create_table(
        'consumer_segments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('person_id', sa.UUID(), nullable=False),
        sa.Column('segment', sa.String(length=100), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        *_TS_COLS,
        sa.ForeignKeyConstraint(['person_id'], ['persons.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_consumer_segment_person_id', 'consumer_segments', ['person_id'])

    # ── ticket_sizes ──────────────────────────────────────────────────────────
    op.create_table(
        'ticket_sizes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('person_id', sa.UUID(), nullable=False),
        sa.Column('estimated_clv_usd', sa.Float(), nullable=True),
        sa.Column('estimated_income_usd', sa.Float(), nullable=True),
        sa.Column('spend_tier', sa.String(length=30), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        *_TS_COLS,
        sa.ForeignKeyConstraint(['person_id'], ['persons.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ticket_size_person_id', 'ticket_sizes', ['person_id'])

    # ── audit_log ─────────────────────────────────────────────────────────────
    op.create_table(
        'audit_log',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('actor_api_key', sa.String(length=64), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('resource_type', sa.String(length=50), nullable=True),
        sa.Column('resource_id', sa.String(length=100), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('request_id', sa.String(length=64), nullable=True),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('access_time', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_actor_access_time', 'audit_log', ['actor_api_key', 'access_time'])
    op.create_index('ix_audit_resource_access_time', 'audit_log', ['resource_type', 'resource_id', 'access_time'])

    # ── search_progress ───────────────────────────────────────────────────────
    op.create_table(
        'search_progress',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('person_id', sa.UUID(), nullable=False),
        sa.Column('search_session_id', sa.String(length=64), nullable=False),
        sa.Column('total_crawlers', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('completed_crawlers', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('found_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='running'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        *_TS_COLS,
        sa.ForeignKeyConstraint(['person_id'], ['persons.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_search_progress_person_status', 'search_progress', ['person_id', 'status'])
    op.create_index('ix_search_progress_session_id', 'search_progress', ['search_session_id'])

    # ── opt_outs ──────────────────────────────────────────────────────────────
    op.create_table(
        'opt_outs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('person_id', sa.UUID(), nullable=True),
        sa.Column('email', sa.String(length=500), nullable=True),
        sa.Column('request_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='pending'),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        *_TS_COLS,
        sa.ForeignKeyConstraint(['person_id'], ['persons.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_opt_out_email', 'opt_outs', ['email'])
    op.create_index(
        'ix_opt_out_person_id',
        'opt_outs',
        ['person_id'],
        postgresql_where=sa.text('person_id IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('ix_opt_out_person_id', table_name='opt_outs')
    op.drop_index('ix_opt_out_email', table_name='opt_outs')
    op.drop_table('opt_outs')

    op.drop_index('ix_search_progress_session_id', table_name='search_progress')
    op.drop_index('ix_search_progress_person_status', table_name='search_progress')
    op.drop_table('search_progress')

    op.drop_index('ix_audit_resource_access_time', table_name='audit_log')
    op.drop_index('ix_audit_actor_access_time', table_name='audit_log')
    op.drop_table('audit_log')

    op.drop_index('ix_ticket_size_person_id', table_name='ticket_sizes')
    op.drop_table('ticket_sizes')

    op.drop_index('ix_consumer_segment_person_id', table_name='consumer_segments')
    op.drop_table('consumer_segments')

    op.drop_index('ix_marketing_tag_person_tag', table_name='marketing_tags')
    op.drop_table('marketing_tags')
