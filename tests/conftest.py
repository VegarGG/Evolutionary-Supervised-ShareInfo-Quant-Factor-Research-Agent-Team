"""All tests are offline except explicitly configured local database/socket checks."""

import socket

import pytest


@pytest.fixture(autouse=True)
def forbid_external_network(monkeypatch):
    original = socket.socket.connect

    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in {
            "127.0.0.1",
            "::1",
            "localhost",
            "postgres",
        }:
            raise AssertionError("Tests must not call external services or real LLM providers")
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)
