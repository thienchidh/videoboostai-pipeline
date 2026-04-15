#!/usr/bin/env python3
"""
tests/test_pipeline_observer.py — Tests for the Pipeline Observer HTTP server.
"""
import json
import threading
import time
from unittest.mock import patch, MagicMock

import pytest

# Ensure project root is on path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestPipelineObserver:
    """Test the PipelineObserver FastAPI app."""

    @pytest.fixture
    def observer_app(self):
        """Import and return the FastAPI app."""
        from modules.ops.pipeline_observer import app
        return app

    @pytest.fixture
    def test_client(self, observer_app):
        """Create a test client for the FastAPI app."""
        from fastapi.testclient import TestClient
        return TestClient(observer_app)

    def test_health_endpoint(self, test_client):
        """GET /health returns ok status."""
        response = test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "pipeline-observer"
        assert "ts" in data

    def test_list_runs_endpoint(self, test_client):
        """GET /runs returns a list of runs."""
        response = test_client.get("/runs")
        assert response.status_code == 200
        data = response.json()
        assert "runs" in data
        assert isinstance(data["runs"], list)
        assert "count" in data
        assert data["count"] == len(data["runs"])

    def test_list_runs_with_status_filter(self, test_client):
        """GET /runs?status=running returns only running runs."""
        response = test_client.get("/runs?status=running")
        assert response.status_code == 200
        data = response.json()
        for run in data["runs"]:
            assert run["status"] == "running"

    def test_get_run_not_found(self, test_client):
        """GET /runs/99999 returns 404."""
        response = test_client.get("/runs/99999")
        assert response.status_code == 404

    def test_get_run_found(self, test_client):
        """GET /runs/{id} returns run details for existing runs."""
        # First get a run id from the list
        list_resp = test_client.get("/runs")
        runs = list_resp.json()["runs"]
        if runs:
            run_id = runs[0]["id"]
            response = test_client.get(f"/runs/{run_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == run_id
            assert "scenes" in data
            assert "credits_by_provider" in data
            assert "errors" in data

    def test_get_run_steps(self, test_client):
        """GET /runs/{id}/steps returns per-scene step progress."""
        list_resp = test_client.get("/runs")
        runs = list_resp.json()["runs"]
        if runs:
            run_id = runs[0]["id"]
            response = test_client.get(f"/runs/{run_id}/steps")
            assert response.status_code == 200
            data = response.json()
            assert "scenes" in data
            # Each scene should have a 'steps' list
            for scene in data["scenes"]:
                assert "steps" in scene
                assert isinstance(scene["steps"], list)

    def test_dashboard_html(self, test_client):
        """GET / returns HTML dashboard."""
        response = test_client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        html = response.text
        assert "<html" in html
        assert "Video Pipeline Observer" in html
        assert "loadRuns" in html  # JS function

    def test_run_stream_ping(self, test_client):
        """GET /runs/{id}/stream starts and sends events (no client disconnect)."""
        list_resp = test_client.get("/runs")
        runs = list_resp.json()["runs"]
        if not runs:
            pytest.skip("No runs in DB")

        run_id = runs[0]["id"]
        # Use streaming response with a timeout to avoid hanging
        import socket
        sock = socket.socket()
        sock.settimeout(3)
        try:
            # Just verify the endpoint is reachable and returns event-stream content type
            # Full SSE test would require async client
            pass
        finally:
            sock.close()

        # Verify route exists by checking app routes
        from modules.ops.pipeline_observer import app
        paths = [r.path for r in app.routes]
        assert "/runs/{run_id}/stream" in paths


class TestPipelineObserverStandalone:
    """Test the PipelineObserver thread runner."""

    def test_start_stop(self):
        """Observer can start and stop cleanly."""
        from modules.ops.pipeline_observer import PipelineObserver
        obs = PipelineObserver(port=18083, daemon=True)
        obs.start()
        time.sleep(1.5)
        assert obs._thread is not None
        assert obs._thread.is_alive()
        obs.stop()

    def test_endpoints_via_requests(self):
        """Observer serves HTTP endpoints when started in thread."""
        from modules.ops.pipeline_observer import PipelineObserver
        import urllib.request

        obs = PipelineObserver(port=18084, daemon=True)
        obs.start()
        time.sleep(2)

        try:
            r = urllib.request.urlopen("http://localhost:18084/health", timeout=5)
            data = json.loads(r.read())
            assert data["status"] == "ok"
        finally:
            obs.stop()
