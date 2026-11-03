"""
Tests for purchase order API endpoints.
"""
import pytest


class TestPurchaseOrderEndpoints:
    """Test suite for purchase-order endpoints."""

    @staticmethod
    def payload(backlog_item_id, **overrides):
        data = {
            "backlog_item_id": backlog_item_id,
            "supplier_name": "Acme Supply",
            "quantity": 350,
            "unit_cost": 12.5,
            "expected_delivery_date": "2025-11-15",
            "notes": "Rush order",
        }
        data.update(overrides)
        return data

    @staticmethod
    def first_backlog_id(client):
        return client.get("/api/backlog").json()[0]["id"]

    def test_backlog_items_start_without_purchase_order(self, client):
        """Test that backlog items expose no purchase order before one is created."""
        for item in client.get("/api/backlog").json():
            assert item["has_purchase_order"] is False
            assert item["purchase_order_id"] is None

    def test_create_purchase_order(self, client):
        """Test creating a purchase order for a backlog item."""
        backlog_id = self.first_backlog_id(client)

        response = client.post("/api/purchase-orders", json=self.payload(backlog_id))
        assert response.status_code == 201

        po = response.json()
        assert po["id"].startswith("PO-")
        assert po["backlog_item_id"] == backlog_id
        assert po["supplier_name"] == "Acme Supply"
        assert po["quantity"] == 350
        assert po["unit_cost"] == 12.5
        assert po["status"] == "Submitted"
        assert po["notes"] == "Rush order"

    def test_created_purchase_order_is_linked_in_backlog(self, client):
        """Test that the backlog reports the new purchase order's id."""
        backlog_id = self.first_backlog_id(client)
        po = client.post("/api/purchase-orders", json=self.payload(backlog_id)).json()

        item = next(i for i in client.get("/api/backlog").json() if i["id"] == backlog_id)
        assert item["has_purchase_order"] is True
        assert item["purchase_order_id"] == po["id"]

    def test_get_purchase_order_by_backlog_item(self, client):
        """Test fetching a purchase order by its backlog item id."""
        backlog_id = self.first_backlog_id(client)
        created = client.post("/api/purchase-orders", json=self.payload(backlog_id)).json()

        response = client.get(f"/api/purchase-orders/{backlog_id}")
        assert response.status_code == 200
        assert response.json() == created

    def test_get_nonexistent_purchase_order(self, client):
        """Test fetching a purchase order for a backlog item that has none."""
        response = client.get("/api/purchase-orders/nonexistent-999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_create_purchase_order_unknown_backlog_item(self, client):
        """Test that an unknown backlog item is rejected."""
        response = client.post("/api/purchase-orders", json=self.payload("nonexistent-999"))
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_create_duplicate_purchase_order(self, client):
        """Test that a backlog item cannot receive a second purchase order."""
        backlog_id = self.first_backlog_id(client)
        assert client.post("/api/purchase-orders", json=self.payload(backlog_id)).status_code == 201

        response = client.post("/api/purchase-orders", json=self.payload(backlog_id))
        assert response.status_code == 400
        assert "already" in response.json()["detail"].lower()

    @pytest.mark.parametrize("overrides", [
        {"supplier_name": "   "},
        {"quantity": 0},
        {"quantity": -5},
        {"unit_cost": 0},
        {"unit_cost": -1.5},
        {"expected_delivery_date": "15/11/2025"},
        {"expected_delivery_date": ""},
    ])
    def test_create_purchase_order_invalid_input(self, client, overrides):
        """Test that invalid field values are rejected without creating an order."""
        backlog_id = self.first_backlog_id(client)

        response = client.post("/api/purchase-orders", json=self.payload(backlog_id, **overrides))
        assert response.status_code == 400
        assert client.get(f"/api/purchase-orders/{backlog_id}").status_code == 404

    def test_create_purchase_order_missing_fields(self, client):
        """Test that a request missing required fields fails validation."""
        response = client.post("/api/purchase-orders", json={"backlog_item_id": "1"})
        assert response.status_code == 422

    def test_create_purchase_order_without_notes(self, client):
        """Test that notes are optional."""
        backlog_id = self.first_backlog_id(client)
        data = self.payload(backlog_id)
        del data["notes"]

        response = client.post("/api/purchase-orders", json=data)
        assert response.status_code == 201
        assert response.json()["notes"] is None
