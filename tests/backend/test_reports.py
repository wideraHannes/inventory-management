"""
Tests for reports API endpoints.
"""
import pytest


class TestReportsEndpoints:
    """Test suite for report-related endpoints."""

    def test_get_quarterly_reports(self, client):
        """Test getting quarterly reports."""
        response = client.get("/api/reports/quarterly")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

        for quarter in data:
            assert "quarter" in quarter
            assert "total_orders" in quarter
            assert "total_revenue" in quarter
            assert "avg_order_value" in quarter
            assert "fulfillment_rate" in quarter
            assert 0 <= quarter["fulfillment_rate"] <= 100

    def test_get_monthly_trends(self, client):
        """Test getting monthly trends sorted by month."""
        response = client.get("/api/reports/monthly-trends")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

        months = [m["month"] for m in data]
        assert months == sorted(months)
        for month in data:
            assert "order_count" in month
            assert "revenue" in month
            assert "delivered_count" in month

    def test_monthly_trends_match_orders(self, client):
        """Test that monthly trends aggregate all orders."""
        orders = client.get("/api/orders").json()
        trends = client.get("/api/reports/monthly-trends").json()

        assert sum(m["order_count"] for m in trends) == len(orders)
        assert abs(sum(m["revenue"] for m in trends) - sum(o["total_value"] for o in orders)) < 1

    def test_get_quarterly_reports_by_warehouse(self, client):
        """Test filtering quarterly reports by warehouse."""
        orders = client.get("/api/orders?warehouse=Tokyo").json()
        data = client.get("/api/reports/quarterly?warehouse=Tokyo").json()

        assert sum(q["total_orders"] for q in data) == len(orders)

    def test_get_monthly_trends_by_quarter(self, client):
        """Test filtering monthly trends by quarter."""
        response = client.get("/api/reports/monthly-trends?month=Q2-2025")
        assert response.status_code == 200

        data = response.json()
        assert len(data) > 0
        for month in data:
            assert month["month"] in ["2025-04", "2025-05", "2025-06"]

    @pytest.mark.parametrize("endpoint", ["quarterly", "monthly-trends"])
    def test_get_reports_multiple_filters(self, client, endpoint):
        """Test that reports respect combined filters like the orders endpoint."""
        query = "warehouse=San Francisco&category=Power Supplies&status=Delivered&month=Q1-2025"
        orders = client.get(f"/api/orders?{query}").json()
        data = client.get(f"/api/reports/{endpoint}?{query}").json()

        count_field = "total_orders" if endpoint == "quarterly" else "order_count"
        assert sum(row[count_field] for row in data) == len(orders)

    def test_quarterly_reports_delivered_status_full_fulfillment(self, client):
        """Test that filtering by Delivered status yields 100% fulfillment."""
        data = client.get("/api/reports/quarterly?status=Delivered").json()

        for quarter in data:
            assert quarter["fulfillment_rate"] == 100.0
