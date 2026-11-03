"""
Tests for restocking order API endpoints.
"""
import pytest
from datetime import date, timedelta


class TestRestockingOrderEndpoints:
    """Test suite for restocking-order endpoints."""

    @staticmethod
    def forecasts_by_sku(client):
        return {f["item_sku"]: f for f in client.get("/api/demand").json()}

    def test_demand_forecasts_include_cost_fields(self, client):
        """Test that forecasts carry the cost and lead-time fields restocking relies on."""
        data = client.get("/api/demand").json()
        assert len(data) > 0

        for forecast in data:
            assert isinstance(forecast["unit_cost"], (int, float))
            assert forecast["unit_cost"] > 0
            assert isinstance(forecast["supplier_name"], str)
            assert isinstance(forecast["lead_time_days"], int)
            assert forecast["lead_time_days"] > 0

    def test_create_restocking_order(self, client):
        """Test submitting a valid restocking order."""
        forecasts = self.forecasts_by_sku(client)
        payload = {"items": [{"item_sku": "WDG-001", "quantity": 100}]}

        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["id"].startswith("RO-")
        assert len(order["items"]) == 1

        line = order["items"][0]
        assert line["item_sku"] == "WDG-001"
        assert line["quantity"] == 100
        assert line["unit_cost"] == forecasts["WDG-001"]["unit_cost"]
        assert abs(line["line_total"] - 100 * forecasts["WDG-001"]["unit_cost"]) < 0.01
        assert abs(order["total_cost"] - line["line_total"]) < 0.01

    def test_restocking_order_lead_time_is_slowest_item(self, client):
        """Test that the order lead time and delivery date follow the slowest item."""
        forecasts = self.forecasts_by_sku(client)
        skus = ["GSK-203", "MTR-304"]
        payload = {"items": [{"item_sku": sku, "quantity": 1} for sku in skus]}

        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        expected_lead_time = max(forecasts[sku]["lead_time_days"] for sku in skus)
        assert order["lead_time_days"] == expected_lead_time

        created = date.fromisoformat(order["created_date"])
        expected_delivery = created + timedelta(days=expected_lead_time)
        assert order["expected_delivery_date"] == expected_delivery.isoformat()

    def test_restocking_order_total_sums_all_lines(self, client):
        """Test that the order total is the sum of its line totals."""
        payload = {
            "items": [
                {"item_sku": "FLT-405", "quantity": 50},
                {"item_sku": "GSK-203", "quantity": 20},
            ]
        }

        order = client.post("/api/restocking-orders", json=payload).json()

        assert abs(order["total_cost"] - sum(l["line_total"] for l in order["items"])) < 0.01

    def test_restocking_order_ignores_client_supplied_price(self, client):
        """Test that a price in the request body does not change the stored unit cost."""
        forecasts = self.forecasts_by_sku(client)
        payload = {"items": [{"item_sku": "WDG-001", "quantity": 1, "unit_cost": 0.01}]}

        order = client.post("/api/restocking-orders", json=payload).json()

        assert order["items"][0]["unit_cost"] == forecasts["WDG-001"]["unit_cost"]

    def test_create_restocking_order_unknown_sku(self, client):
        """Test that an unknown SKU is rejected."""
        response = client.post(
            "/api/restocking-orders",
            json={"items": [{"item_sku": "NOPE-999", "quantity": 1}]},
        )
        assert response.status_code == 400
        assert "unknown sku" in response.json()["detail"].lower()

    @pytest.mark.parametrize("quantity", [0, -5])
    def test_create_restocking_order_rejects_non_positive_quantity(self, client, quantity):
        """Test that zero and negative quantities are rejected."""
        response = client.post(
            "/api/restocking-orders",
            json={"items": [{"item_sku": "WDG-001", "quantity": quantity}]},
        )
        assert response.status_code == 400

    def test_create_restocking_order_empty_items(self, client):
        """Test that an order with no items is rejected."""
        response = client.post("/api/restocking-orders", json={"items": []})
        assert response.status_code == 400

    def test_create_restocking_order_duplicate_sku(self, client):
        """Test that the same SKU twice in one order is rejected."""
        response = client.post(
            "/api/restocking-orders",
            json={
                "items": [
                    {"item_sku": "WDG-001", "quantity": 1},
                    {"item_sku": "WDG-001", "quantity": 2},
                ]
            },
        )
        assert response.status_code == 400
        assert "duplicate" in response.json()["detail"].lower()

    def test_create_restocking_order_malformed_body(self, client):
        """Test that a body missing required fields fails validation."""
        response = client.post("/api/restocking-orders", json={"items": [{"item_sku": "WDG-001"}]})
        assert response.status_code == 422

    def test_rejected_order_is_not_stored(self, client):
        """Test that a rejected order leaves the stored orders unchanged."""
        before = client.get("/api/restocking-orders").json()

        client.post(
            "/api/restocking-orders",
            json={
                "items": [
                    {"item_sku": "WDG-001", "quantity": 1},
                    {"item_sku": "NOPE-999", "quantity": 1},
                ]
            },
        )

        assert client.get("/api/restocking-orders").json() == before

    def test_get_restocking_orders_lists_created_order_first(self, client):
        """Test that GET returns the newest order first."""
        created = client.post(
            "/api/restocking-orders",
            json={"items": [{"item_sku": "FLT-405", "quantity": 10}]},
        ).json()

        response = client.get("/api/restocking-orders")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert data[0]["id"] == created["id"]

    def test_restocking_order_ids_are_unique(self, client):
        """Test that consecutive orders get different ids."""
        payload = {"items": [{"item_sku": "FLT-405", "quantity": 1}]}

        first = client.post("/api/restocking-orders", json=payload).json()
        second = client.post("/api/restocking-orders", json=payload).json()

        assert first["id"] != second["id"]
