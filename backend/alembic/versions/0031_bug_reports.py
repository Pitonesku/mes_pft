"""Bug reports (web console + tablet) with attachments

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-02

Additive tables for user-submitted bug / suggestion reports: text (max 2000
chars), submitter snapshot, status lifecycle (NEW / IN_PROGRESS / RESOLVED)
and BYTEA attachments (images/screenshots, up to 3 per report).
"""

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS bug_reports (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NULL REFERENCES users(id),
            username VARCHAR(120) NOT NULL,
            source VARCHAR(20) NOT NULL DEFAULT 'web',
            text VARCHAR(2000) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            status VARCHAR(20) NOT NULL DEFAULT 'NEW',
            resolved_by VARCHAR(120) NULL,
            resolved_at TIMESTAMPTZ NULL,
            resolution_note VARCHAR(2000) NULL
        );
        CREATE TABLE IF NOT EXISTS bug_report_attachments (
            id BIGSERIAL PRIMARY KEY,
            bug_report_id BIGINT NOT NULL REFERENCES bug_reports(id),
            filename VARCHAR(255) NOT NULL,
            mime VARCHAR(100) NOT NULL,
            size_bytes INTEGER NOT NULL,
            data BYTEA NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_bug_reports_created ON bug_reports (created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_bug_report_attachments_report ON bug_report_attachments (bug_report_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS bug_report_attachments;
        DROP TABLE IF EXISTS bug_reports;
        """
    )
