"""Offline bearer verification; synthetic ephemeral tokens, no deployed grants."""

import secrets

import pytest
from pydantic import ValidationError
from qfr_core.access import AuthenticationRequired, BearerAuthority, ServicePrincipal
from qfr_core.contracts.access import ServiceAuthentication


def configuration(**change):
    value = dict(
        revision=1,
        audience="feedback",
        minimum_token_bytes=32,
        maximum_token_bytes=4096,
        bindings=[
            dict(
                principal="reader",
                token_ref="env:QFR_SYNTHETIC_READER",
                roles=["reader"],
                programs=["program-one"],
            )
        ],
    )
    value.update(change)
    return ServiceAuthentication.model_validate(value)


def test_bearer_is_exact_audience_scoped_and_never_reads_unrelated_credentials():
    token = secrets.token_urlsafe(32)

    class ExplicitEnvironment(dict):
        def get(self, key, default=None):
            assert key == "QFR_SYNTHETIC_READER"
            return super().get(key, default)

        def __iter__(self):
            raise AssertionError("must not enumerate credentials")

    auth = BearerAuthority(configuration(), ExplicitEnvironment(QFR_SYNTHETIC_READER=token))
    result = auth.authenticate(["Bearer " + token], audience="feedback")
    assert result.programs == {"program-one"} and result.roles == {"reader"}
    assert token not in repr(auth._tokens) and token not in auth.config.model_dump_json()
    for headers in (
        [],
        ["Bearer " + token, "Bearer " + token],
        ["Bearer  " + token],
        ["Basic " + token],
        ["Bearer bad"],
        ["Bearer " + token + "x"],
    ):
        with pytest.raises(AuthenticationRequired):
            auth.authenticate(headers, audience="feedback")
    with pytest.raises(AuthenticationRequired):
        auth.authenticate(["Bearer " + token], audience="research")


@pytest.mark.parametrize("program", ["*", "one,two", "one\ntwo", "", "'; SELECT 1"])
def test_program_scope_cannot_inject_guc_delimiters_or_wildcards(program):
    with pytest.raises((ValidationError, ValueError)):
        ServicePrincipal("reader", "feedback", frozenset({"reader"}), frozenset({program}))


def test_missing_or_duplicate_token_and_evaluator_role_fail_configuration():
    with pytest.raises(ValueError, match="missing or invalid"):
        BearerAuthority(configuration(), {})
    bad = configuration().model_dump()
    bad["bindings"][0]["roles"] = ["evaluation_owner"]
    with pytest.raises(ValidationError):
        ServiceAuthentication.model_validate(bad)
    bad["bindings"][0]["roles"] = ["research_lead"]
    with pytest.raises(ValidationError, match="only reader"):
        ServiceAuthentication.model_validate(bad)
    token = secrets.token_urlsafe(32)
    duplicate = configuration().model_dump()
    duplicate["bindings"].append({**duplicate["bindings"][0], "token_ref": "env:QFR_OTHER_TOKEN"})
    with pytest.raises(ValueError, match="distinct"):
        BearerAuthority(
            ServiceAuthentication.model_validate(duplicate),
            {"QFR_SYNTHETIC_READER": token, "QFR_OTHER_TOKEN": token},
        )


@pytest.mark.parametrize("profile", ["pilot", "stock"])
def test_owner_policy_hash_command_is_offline_and_matches_the_exact_policy(profile, capsys):
    from pathlib import Path

    from qfr_eval.admin.cli import main
    from qfr_eval.release.store import POLICY

    path = Path(f"configs/evaluation/release_{profile}_v1.json")
    main(["policy-hash", str(path)])
    assert capsys.readouterr().out.strip() == POLICY.validate_json(path.read_bytes()).sha256
