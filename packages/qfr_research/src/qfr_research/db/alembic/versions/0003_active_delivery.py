"""Bind receipt acceptance and human approval to the current immutable proposal."""

from alembic import op

revision = "0003_active_delivery"
down_revision = "0002_human_api"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      ALTER TABLE research.research_jobs ADD COLUMN active_delivery_proposal_id uuid,
        ADD FOREIGN KEY(active_delivery_proposal_id,program_id)
          REFERENCES research.delivery_proposals(id,program_id);
      CREATE UNIQUE INDEX one_approval_checkpoint_per_proposal
        ON research.checkpoints(program_id,research_job_id,(payload#>>'{request,proposal_id}'))
        WHERE payload#>>'{request,kind}'='delivery_approval';
    """)


def downgrade() -> None:
    raise RuntimeError("Delivery proposal and human approval history cannot be downgraded")
