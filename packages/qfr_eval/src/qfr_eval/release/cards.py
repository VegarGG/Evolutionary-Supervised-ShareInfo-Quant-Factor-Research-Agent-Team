"""Evaluator-owned public-card projection; never serialize a private protocol."""

from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg import Connection
from psycopg.types.json import Jsonb
from qfr_core.contracts.reports import PublicProtocolCard, PublicReleasePolicyCard

from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.release.models import PilotReleasePolicy
from qfr_eval.release.policy import public_card
from qfr_eval.release.store import active_policy
from qfr_eval.scheduler.dedup import digest


def pilot_protocol_card(protocol: FrozenProtocol, policy: PilotReleasePolicy) -> PublicProtocolCard:
    if protocol.sha256 != policy.protocol_sha256 or protocol.scope != "P0_P1_verification_only":
        raise ValueError("public pilot card requires its exact approved protocol")
    return PublicProtocolCard(
        schema_version="1",
        protocol_version=f"{protocol.protocol_id}@{protocol.version}",
        profile="pilot_industry_v1",
        universe="31 pilot industries; p60 eligible observations",
        label_definition=(
            "Original cycle-matched mature holding periods; "
            "preserved original eligibility and warm-up"
        ),
        metric_definitions={
            "extreme_macro_recall": (
                "Mean recall of original extreme groups over mature matched decisions; ratio unit"
            )
        },
        cost_policy_ref=f"{protocol.protocol_id}@{protocol.version}:primary_cost_bps_10",
        public_gate_descriptions=[
            "Frozen paired comparison with P1",
            "Coverage and causal execution",
            "Paired uncertainty and family correction",
            "Approved turnover and stability checks",
            "Insufficient data cannot pass",
        ],
        release_policy_ref=f"{policy.policy_id}@{policy.version}",
        exposure="previously_seen",
    )


def store_card(
    conn: Connection,
    card: PublicProtocolCard | PublicReleasePolicyCard,
    *,
    principal: str,
    request_id: UUID,
) -> str:
    if not principal.strip():
        raise ValueError("card author required")
    table = (
        "public_policy_cards"
        if isinstance(card, PublicReleasePolicyCard)
        else "public_protocol_cards"
    )
    ref = card.policy_ref if isinstance(card, PublicReleasePolicyCard) else card.protocol_version
    body = card.model_dump(mode="json")
    sha = digest(body)
    key = uuid5(NAMESPACE_URL, "qfr-public-card:" + table + ":" + ref)
    with conn.transaction():
        row = conn.execute(
            "INSERT INTO eval."
            + table
            + "(id,payload,card_ref,content_sha256,created_by,request_id) "
            "VALUES(%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(card_ref) DO NOTHING RETURNING content_sha256",
            [key, Jsonb(body), ref, sha, principal, request_id],
        ).fetchone()
        if row is None:
            previous = conn.execute(
                "SELECT content_sha256 FROM eval." + table + " WHERE card_ref=%s", [ref]
            ).fetchone()
            if previous != (sha,):
                raise ValueError("public card reference already has different content")
    return sha


def publish_policy_cards(
    conn: Connection, policy_hash: str, *, principal: str, request_id: UUID
) -> list[str]:
    with conn.transaction():
        policy = active_policy(conn, policy_hash)
        hashes = [store_card(conn, public_card(policy), principal=principal, request_id=request_id)]
        if isinstance(policy, PilotReleasePolicy):
            row = conn.execute(
                "SELECT payload FROM eval.protocols WHERE sha256=%s AND status='active'",
                [policy.protocol_sha256],
            ).fetchone()
            if row is None:
                raise ValueError("pilot public card requires its active protocol")
            card = pilot_protocol_card(FrozenProtocol.model_validate(row[0]), policy)
            hashes.append(store_card(conn, card, principal=principal, request_id=request_id))
        # Stock protocol fields are not guessed from a release-policy profile.
        return hashes
