"""runs.trigger may be 'simulated' (seeded demo history, marked in the dashboard)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-22
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_trigger", "runs", type_="check")
    op.create_check_constraint(
        "ck_trigger", "runs", "trigger IN ('schedule', 'manual', 'simulated')"
    )


def downgrade() -> None:
    # simulated runs cannot exist under the old rule: remove them (their accuracy rows cascade)
    op.execute("DELETE FROM runs WHERE trigger = 'simulated'")
    op.drop_constraint("ck_trigger", "runs", type_="check")
    op.create_check_constraint("ck_trigger", "runs", "trigger IN ('schedule', 'manual')")
