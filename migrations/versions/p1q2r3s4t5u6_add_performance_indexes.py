"""add_performance_indexes

Revision ID: p1q2r3s4t5u6
Revises: k1l2m3n4o5p6
Create Date: 2026-03-29 00:00:00.000000

"""

from alembic import op

revision = "p1q2r3s4t5u6"
down_revision = "k1l2m3n4o5p6"
branch_labels = None
depends_on = None


def upgrade():
    # Social profile lookup
    op.create_index("ix_social_profile_platform_handle", "social_profiles", ["platform", "handle"], if_not_exists=True)
    # Crawl job dispatch
    op.create_index("ix_crawl_job_person_status", "crawl_jobs", ["person_id", "status"], if_not_exists=True)


def downgrade():
    op.drop_index("ix_social_profile_platform_handle", table_name="social_profiles")
    op.drop_index("ix_crawl_job_person_status", table_name="crawl_jobs")
