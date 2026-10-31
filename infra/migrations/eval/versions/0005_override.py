"""Phase 8 eval_db (PLAN Sections 10.3 and 10.5, P8.7): the owner override for acceptance.

In v1 a case with a failed gate can never be accepted. Phase 8 lets the owner accept one
in two steps: an override request with a written rationale (at least 200 characters)
opens a 24-hour cooling period, and a second, separate approval given after it confirms.
Only then is the case decided as accepted, with the reason owner_override and the gate
it overrode.

The override row is insert-only apart from its one transition (pending to confirmed or
withdrawn). The case's guard refuses an owner_override decision unless the override was
confirmed with the decision's own approval after its cooling period; a rejection
withdraws a pending override.
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

REASONS = ("gate_failed", "owner_rejected", "incubation_failed", "gates_passed", "owner_override")
FIXED = (
    "ARRAY['state', 'decision', 'reason', 'reason_gate', 'rationale', 'approval_id', "
    "'decided_by', 'decided_at']"
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade():
    op.execute("""CREATE TABLE eval.acceptance_overrides (
        case_id uuid PRIMARY KEY REFERENCES eval.acceptance_cases (case_id),
        requested_at timestamptz NOT NULL,
        eligible_at timestamptz NOT NULL,
        rationale text NOT NULL CHECK (length(rationale) BETWEEN 200 AND 4000),
        failing_gates text[] NOT NULL CHECK (cardinality(failing_gates) >= 1),
        request_approval_id uuid NOT NULL,
        requested_by text NOT NULL,
        state text NOT NULL CHECK (state IN ('pending', 'confirmed', 'withdrawn')),
        confirm_approval_id uuid,
        confirmed_by text,
        confirmed_at timestamptz,
        withdrawn_at timestamptz,
        request_id text NOT NULL,
        CHECK (eligible_at >= requested_at + interval '24 hours'),
        CHECK ((state = 'confirmed') = (confirm_approval_id IS NOT NULL
                                        AND confirmed_at IS NOT NULL
                                        AND confirmed_by IS NOT NULL)),
        CHECK ((state = 'withdrawn') = (withdrawn_at IS NOT NULL)),
        CHECK (confirmed_at IS NULL OR confirmed_at >= eligible_at),
        CHECK (confirm_approval_id IS DISTINCT FROM request_approval_id)
    )""")
    op.execute("REVOKE DELETE, TRUNCATE ON eval.acceptance_overrides FROM eval_rw")
    op.execute("""CREATE FUNCTION eval.guard_acceptance_override() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.state <> 'pending' THEN
                    RAISE EXCEPTION 'an override starts pending';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP <> 'UPDATE' THEN RAISE EXCEPTION 'overrides are never deleted'; END IF;
            IF OLD.state <> 'pending' OR NEW.state NOT IN ('confirmed', 'withdrawn') THEN
                RAISE EXCEPTION 'an override is confirmed or withdrawn once';
            END IF;
            IF (to_jsonb(NEW) - ARRAY['state', 'confirm_approval_id', 'confirmed_by',
                                      'confirmed_at', 'withdrawn_at'])
               IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['state', 'confirm_approval_id', 'confirmed_by',
                                      'confirmed_at', 'withdrawn_at']) THEN
                RAISE EXCEPTION 'an override''s request is immutable';
            END IF;
            RETURN NEW;
        END; $$""")
    op.execute("""CREATE TRIGGER acceptance_overrides_guard
        BEFORE INSERT OR UPDATE OR DELETE ON eval.acceptance_overrides
        FOR EACH ROW EXECUTE FUNCTION eval.guard_acceptance_override()""")
    op.execute("""CREATE TRIGGER acceptance_overrides_no_truncate
        BEFORE TRUNCATE ON eval.acceptance_overrides
        FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()""")

    op.execute("ALTER TABLE eval.acceptance_cases DROP CONSTRAINT acceptance_cases_reason_check")
    op.execute(
        "ALTER TABLE eval.acceptance_cases ADD CONSTRAINT acceptance_cases_reason_check "
        f"CHECK (reason IN ({_in(REASONS)}))"
    )
    # ACC-03 keeps holding except through a confirmed override.
    op.execute("ALTER TABLE eval.acceptance_cases DROP CONSTRAINT acceptance_cases_check3")
    op.execute("""ALTER TABLE eval.acceptance_cases ADD CONSTRAINT acceptance_cases_accept_check
        CHECK (decision IS DISTINCT FROM 'accepted' OR recommendation = 'ACCEPT'
               OR reason = 'owner_override')""")
    op.execute("""ALTER TABLE eval.acceptance_cases ADD CONSTRAINT acceptance_cases_override_check
        CHECK (reason IS DISTINCT FROM 'owner_override'
               OR (decision = 'accepted' AND recommendation = 'REJECT'))""")
    op.execute(f"""CREATE OR REPLACE FUNCTION eval.guard_acceptance_case() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE sim eval.sim_accounts%ROWTYPE;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                SELECT * INTO sim FROM eval.sim_accounts WHERE sim_id = NEW.sim_id;
                IF sim.purpose IS DISTINCT FROM 'incubation'
                   OR sim.version_id IS DISTINCT FROM NEW.version_id
                   OR sim.status NOT IN ('completed', 'failed')
                   OR (sim.status = 'completed' AND sim.days_done < sim.required_days) THEN
                    RAISE EXCEPTION 'an acceptance case opens only after incubation ends';
                END IF;
                IF NEW.state <> 'open' THEN
                    RAISE EXCEPTION 'an acceptance case opens undecided';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP <> 'UPDATE' THEN RAISE EXCEPTION 'acceptance cases are never deleted'; END IF;
            IF OLD.state <> 'open' OR NEW.state <> 'decided' THEN
                RAISE EXCEPTION 'an acceptance case is decided once';
            END IF;
            IF (to_jsonb(NEW) - {FIXED}) IS DISTINCT FROM (to_jsonb(OLD) - {FIXED}) THEN
                RAISE EXCEPTION 'an acceptance case''s gates are immutable';
            END IF;
            IF NEW.reason = 'owner_override' AND NOT EXISTS (
                SELECT 1 FROM eval.acceptance_overrides o
                WHERE o.case_id = NEW.case_id AND o.state = 'confirmed'
                  AND o.confirm_approval_id = NEW.approval_id
                  AND o.confirmed_at >= o.eligible_at AND o.confirmed_at <= NEW.decided_at
            ) THEN
                RAISE EXCEPTION 'an owner override needs its confirmation after the cooling period';
            END IF;
            RETURN NEW;
        END; $$""")


def downgrade():
    raise RuntimeError("Evaluation migrations are append-only; restore into a new database.")
