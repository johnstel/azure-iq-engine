"""
Tests for GET /health and GET /info endpoints.
"""

from __future__ import annotations


def test_health_returns_200(client):
    resp = client.get("/health")
    assert resp.status_code == 200


def test_health_body(client):
    resp = client.get("/health")
    data = resp.json()
    assert data["status"] == "healthy"
    assert "version" in data


def test_info_returns_200(client):
    resp = client.get("/info")
    assert resp.status_code == 200


def test_info_body_fields(client):
    resp = client.get("/info")
    data = resp.json()
    assert "name" in data
    assert "version" in data
    assert "description" in data
    assert isinstance(data["sources"], list)
    assert isinstance(data["agents"], list)
    assert isinstance(data["iq_layers"], list)


def test_info_iq_layers(client):
    resp = client.get("/info")
    layers = resp.json()["iq_layers"]
    assert "work-iq" in layers
    assert "fabric-iq" in layers
    assert "foundry-iq" in layers


def test_info_agents_non_empty(client):
    resp = client.get("/info")
    agents = resp.json()["agents"]
    assert len(agents) > 0
