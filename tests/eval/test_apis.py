"""feedback-api (P3.6, BND-03) and eval-admin-api (P3.7), over the rig's eval_db."""

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.eval.stack_rig import eval_apps
from tests.mcp.setup_rig import EVAL_TOKENS
from tests.registry_rig import factor_manifest

pytestmark = pytest.mark.postgres


@pytest.fixture
def clients(rig):
    admin_app, feedback_app = eval_apps(rig)
    with (
        TestClient(admin_app, base_url="http://eval-admin-api:8000") as admin,
        TestClient(feedback_app, base_url="http://feedback-api:8000") as feedback,
    ):
        admin.headers["Authorization"] = f"Bearer {EVAL_TOKENS['eval-admin-api']}"
        feedback.headers["Authorization"] = f"Bearer {EVAL_TOKENS['feedback-api']}"
        yield admin, feedback


def test_bnd_03_feedback_openapi_has_only_get_operations(clients):
    _, feedback = clients
    document = feedback.app.openapi()
    methods = {m for operations in document["paths"].values() for m in operations}
    assert methods == {"get"}
    assert set(document["paths"]) == {
        "/healthz", "/v1/reports", "/v1/reports/{report_id}",
        "/v1/artifacts/{version_id}/status", "/v1/library", "/v1/cards/policy",
        "/v1/cards/protocol",
    }  # fmt: skip
    for path in ("/v1/reports", "/v1/library"):
        assert feedback.post(path, json={}).status_code == 405


def test_bnd_03_feedback_serves_only_released_reports(rig, clients):
    _, feedback = clients
    rig.registry.publish(factor_manifest("one", "Pct($close, 20)"))
    rig.cycle()
    queued = rig.db.scalar("SELECT count(*) FROM eval.release_queue WHERE state = 'queued'")
    assert queued == 3
    assert feedback.get("/v1/reports").json() == {"items": [], "next_after_id": None}
    rig.release.tick()
    items = feedback.get("/v1/reports").json()["items"]
    stored = {
        str(r.report_id): r.report
        for r in rig.db.rows("SELECT report_id, report FROM eval.released_reports")
    }
    assert {i["report_id"]: i for i in items} == stored
    page = feedback.get("/v1/reports", params={"limit": 2}).json()
    rest = feedback.get("/v1/reports", params={"after_id": page["next_after_id"]}).json()
    assert len(page["items"]) == 2 and len(rest["items"]) == 1
    assert (
        feedback.get("/v1/reports", params={"type": "w1"}).json()["items"][0]["content"]["type"]
        == "w1"
    )


def test_feedback_requires_the_reader_token_and_never_leaks_internals(clients):
    _, feedback = clients
    assert feedback.get("/v1/reports", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert feedback.get("/healthz", headers={"Authorization": ""}).status_code == 200
    missing = feedback.get("/v1/reports/0190b9b2-7a4e-7cc0-8000-000000000000")
    assert missing.status_code == 404 and missing.json()["error"] == "REPORT_NOT_FOUND"
    bad = feedback.get("/v1/reports", params={"limit": 999999})
    assert bad.status_code == 400 and "Traceback" not in bad.text


def test_cards_follow_the_active_versions(rig, clients):
    admin, feedback = clients
    rig.scheduler.tick()
    protocol = feedback.get("/v1/cards/protocol").json()
    policy = feedback.get("/v1/cards/policy").json()
    assert protocol["ref"] == "cn_csi300_daily/1"
    assert policy["ref"] == "default/1+quotas:default/1"
    assert policy["card"]["quotas"]["family"]["w1_count"] == 3
    shipped = json.loads(Path("configs/public_cards.json").read_text())
    assert protocol["card"] == shipped["protocol"]
    assert policy["card"] == shipped["policy"]
    for private in ("W1", "W2", "W3", "holdout", "acceptance", "2020-"):
        assert private not in json.dumps(protocol["card"])

    raw = Path("configs/quotas/default_v1.yaml").read_text()
    created = admin.post("/v1/quotas", json={"yaml": raw.replace("version: '1'", "version: '2'")
                                              .replace("w1_count: 3", "w1_count: 2")})  # fmt: skip
    assert created.status_code == 201 and created.json()["status"] == "draft"
    again = admin.post("/v1/quotas", json={"yaml": raw.replace("version: '1'", "version: '2'")
                                            .replace("w1_count: 3", "w1_count: 2")})  # fmt: skip
    assert again.status_code == 200 and again.json()["created"] is False
    clash = admin.post("/v1/quotas", json={"yaml": raw.replace("version: '1'", "version: '2'")})
    assert clash.status_code == 409 and clash.json()["error"] == "VERSION_IMMUTABLE"
    active = admin.post("/v1/quotas/default/2/activate", json={})
    assert active.status_code == 200 and active.json()["status"] == "active"
    listed = {v["version"]: v["status"] for v in admin.get("/v1/quotas").json()}
    assert listed == {"1": "retired", "2": "active"}
    assert feedback.get("/v1/cards/policy").json()["card"]["quotas"]["family"]["w1_count"] == 2
    invalid = admin.post("/v1/quotas", json={"yaml": "quota_id: x\nversion: '3'\n"})
    assert invalid.status_code in (400, 422)


def test_admin_routes_serve_owner_reads(rig, clients):
    admin, _ = clients
    version = rig.registry.publish(factor_manifest("owner", "Pct($close, 20)")).json()["version"]
    rig.cycle()
    vid = version["version_id"]
    assert admin.get("/v1/reports").status_code == 404  # no report routes on the admin API
    intake = admin.get("/v1/intake").json()["items"]
    assert [i["version_id"] for i in intake] == [vid]
    states = admin.get("/v1/versions/state", params={"version_id": vid}).json()["items"]
    assert states[0]["evidence_tier"] in ("w1_pass", "w1_fail")
    assert states[0]["released_state"] is None  # nothing released yet
    runs = admin.get("/v1/runs", params={"version_id": vid}).json()["items"]
    assert {r["stage"] for r in runs} == {"screening", "w1"}
    records = admin.get(f"/v1/records/{vid}").json()
    assert [r["stage"] for r in records] == ["screening", "w1"]
    w1_run = next(r for r in runs if r["stage"] == "w1")
    series = admin.get(f"/v1/series/{w1_run['run_id']}/rankic")
    assert series.status_code == 200 and len(series.content) > 0
    assert admin.get(f"/v1/series/{w1_run['run_id']}/factor_values").status_code == 404
    burn = admin.get("/v1/burn").json()
    assert next(m for m in burn["items"] if m["window_name"] == "W1")["trials"] == 1
    usage = admin.get("/v1/quotas/usage").json()
    assert usage["items"]
    private = admin.get("/v1/config/private").json()
    assert private["visibility"] == "owner_only" and "W3" in private["epoch"]["windows"]
    summary = admin.get("/v1/summary").json()
    assert summary["ready"] is True and summary["release"] == {"queued": 3, "released": 0}
    assert admin.get("/v1/summary", headers={"Authorization": "Bearer x"}).status_code == 401
    feedback_token = {"Authorization": f"Bearer {EVAL_TOKENS['feedback-api']}"}
    assert admin.get("/v1/summary", headers=feedback_token).status_code == 401
