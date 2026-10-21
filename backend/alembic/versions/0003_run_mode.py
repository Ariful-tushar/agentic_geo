"""runs.mode and daily_accuracy.mode: dev and live runs of the same day are separate

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21
"""
import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # runs: add mode (existing rows get it from details->>'mode', written by Ax since D2.2)
    op.add_column("runs", sa.Column("mode", sa.Text(), server_default="live", nullable=False))
    op.execute("UPDATE runs SET mode = 'dev' WHERE details->>'mode' = 'dev'")
    op.create_check_constraint("ck_mode", "runs", "mode IN ('dev', 'live')")
    op.drop_constraint("runs_company_id_kind_run_date_key", "runs", type_="unique")
    op.create_unique_constraint(
        "runs_company_id_kind_run_date_mode_key", "runs", ["company_id", "kind", "run_date", "mode"]
    )

    # daily_accuracy: copy the mode of its run
    op.add_column(
        "daily_accuracy", sa.Column("mode", sa.Text(), server_default="live", nullable=False)
    )
    op.execute(
        "UPDATE daily_accuracy d SET mode = r.mode FROM runs r WHERE r.id = d.run_id"
    )
    op.create_check_constraint("ck_mode", "daily_accuracy", "mode IN ('dev', 'live')")
    op.drop_constraint("daily_accuracy_company_id_run_date_engine_key", "daily_accuracy", type_="unique")
    op.create_unique_constraint(
        "daily_accuracy_company_id_run_date_engine_mode_key",
        "daily_accuracy",
        ["company_id", "run_date", "engine", "mode"],
    )


def downgrade() -> None:
    op.drop_constraint("daily_accuracy_company_id_run_date_engine_mode_key", "daily_accuracy", type_="unique")
    op.create_unique_constraint(
        "daily_accuracy_company_id_run_date_engine_key",
        "daily_accuracy",
        ["company_id", "run_date", "engine"],
    )
    op.drop_constraint("ck_mode", "daily_accuracy", type_="check")
    op.drop_column("daily_accuracy", "mode")

    op.drop_constraint("runs_company_id_kind_run_date_mode_key", "runs", type_="unique")
    op.create_unique_constraint(
        "runs_company_id_kind_run_date_key", "runs", ["company_id", "kind", "run_date"]
    )
    op.drop_constraint("ck_mode", "runs", type_="check")
    op.drop_column("runs", "mode")
