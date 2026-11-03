"""
Tests for restocking API endpoints.
"""
from datetime import datetime, timedelta

import pytest

import main


@pytest.fixture(autouse=True)
def clear_restocking_orders():
    """Reset the in-memory restocking orders so each test runs in isolation."""
    main.restocking_orders.clear()
    yield
    main.restocking_orders.clear()


@pytest.fixture
def restock_payload():
    """Valid restocking order request with two items."""
    return {
        "budget": 10000,
        "items": [
            {"sku": "WDG-001", "name": "Industrial Widget Type A", "quantity": 100, "unit_cost": 45.5, "lead_time_days": 14},
            {"sku": "FLT-405", "name": "Oil Filter Cartridge", "quantity": 150, "unit_cost": 12.4, "lead_time_days": 5},
        ],
    }


class TestRestockingEndpoints:
    """Test suite for restocking-related endpoints."""

    def test_demand_forecast_cost_fields(self, client):
        """Test that demand forecasts include unit cost and lead time for restocking."""
        response = client.get("/api/demand")
        assert response.status_code == 200

        for forecast in response.json():
            assert isinstance(forecast["unit_cost"], (int, float))
            assert isinstance(forecast["lead_time_days"], int)
            assert forecast["unit_cost"] > 0
            assert forecast["lead_time_days"] > 0

    def test_get_restocking_orders_empty(self, client):
        """Test that no restocking orders exist initially."""
        response = client.get("/api/restocking-orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_restocking_order(self, client, restock_payload):
        """Test submitting a valid restocking order."""
        response = client.post("/api/restocking-orders", json=restock_payload)
        assert response.status_code == 201

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["order_number"].startswith("RST-")
        assert len(order["items"]) == 2
        assert order["budget"] == 10000

    def test_restocking_order_total_cost_calculation(self, client, restock_payload):
        """Test that total cost is computed server-side from items."""
        order = client.post("/api/restocking-orders", json=restock_payload).json()

        expected = 100 * 45.5 + 150 * 12.4
        assert abs(order["total_cost"] - expected) < 0.01

    def test_restocking_order_lead_time_calculation(self, client, restock_payload):
        """Test that order lead time is the longest item lead time."""
        order = client.post("/api/restocking-orders", json=restock_payload).json()

        assert order["lead_time_days"] == 14
        order_date = datetime.fromisoformat(order["order_date"])
        expected_delivery = datetime.fromisoformat(order["expected_delivery"])
        assert expected_delivery - order_date == timedelta(days=14)

    def test_create_restocking_order_over_budget(self, client, restock_payload):
        """Test that orders exceeding the budget are rejected."""
        restock_payload["budget"] = 100
        response = client.post("/api/restocking-orders", json=restock_payload)
        assert response.status_code == 400
        assert "budget" in response.json()["detail"].lower()

    def test_create_restocking_order_empty_items(self, client):
        """Test that orders without items are rejected."""
        response = client.post("/api/restocking-orders", json={"budget": 1000, "items": []})
        assert response.status_code == 422

    def test_create_restocking_order_invalid_quantity(self, client, restock_payload):
        """Test that non-positive quantities are rejected."""
        restock_payload["items"][0]["quantity"] = 0
        response = client.post("/api/restocking-orders", json=restock_payload)
        assert response.status_code == 422

    def test_restocking_order_uses_catalog_unit_cost(self, client, restock_payload):
        """Test that a tampered client unit_cost is ignored in favor of the forecast price."""
        restock_payload["items"][0]["unit_cost"] = 0
        restock_payload["budget"] = 2000
        response = client.post("/api/restocking-orders", json=restock_payload)
        assert response.status_code == 400

    def test_create_restocking_order_unknown_sku(self, client, restock_payload):
        """Test that SKUs not in the demand forecast are rejected."""
        restock_payload["items"][0]["sku"] = "NOPE-999"
        response = client.post("/api/restocking-orders", json=restock_payload)
        assert response.status_code == 400
        assert "unknown sku" in response.json()["detail"].lower()

    def test_create_restocking_order_duplicate_sku(self, client, restock_payload):
        """Test that duplicate SKUs in one order are rejected."""
        restock_payload["items"][1]["sku"] = "WDG-001"
        response = client.post("/api/restocking-orders", json=restock_payload)
        assert response.status_code == 400
        assert "duplicate" in response.json()["detail"].lower()

    def test_get_restocking_orders_newest_first(self, client, restock_payload):
        """Test that submitted orders are listed newest first."""
        first = client.post("/api/restocking-orders", json=restock_payload).json()
        second = client.post("/api/restocking-orders", json=restock_payload).json()

        response = client.get("/api/restocking-orders")
        assert response.status_code == 200

        data = response.json()
        assert [o["id"] for o in data] == [second["id"], first["id"]]
        assert first["order_number"] != second["order_number"]
