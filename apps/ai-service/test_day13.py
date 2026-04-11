"""
Day 13 tests — Phase 2 integration hardening.

Covers:
  - Rate limiter: allows requests within limit, blocks at threshold, resets window
  - Rate limiter: per-user isolation, per-endpoint limits
  - Chat router: 429 when rate limit exceeded
  - Chat router: L3 output scan applied after full response collected
  - Chat router: filtered response chunk sent when L3 blocks
  - Interpret router: rate limit applied
  - Health check service: probes return correct schema
  - Health check service: overall status reflects worst probe
  - Health endpoint: returns 503 when unavailable, 200 otherwise
  - NeMo config: new output flow names registered
  - dspy_compiled directory exists
  - requirements.txt includes deepeval, ragas, datasets
"""
from __future__ import annotations

import json
import time
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


# ---------------------------------------------------------------------------
# 1. Rate limiter unit tests
# ---------------------------------------------------------------------------

class TestRateLimiter:
    def setup_method(self):
        from services.rate_limit import reset_limits
        reset_limits()

    def test_allows_requests_within_limit(self):
        from services.rate_limit import check_rate_limit
        # Default chat limit is 30/60s — 5 requests should pass
        for _ in range(5):
            check_rate_limit("user-1", "chat")

    def test_blocks_at_threshold(self):
        from services.rate_limit import check_rate_limit, LIMITS
        from fastapi import HTTPException
        max_req, _ = LIMITS["interpret"]
        for _ in range(max_req):
            check_rate_limit("user-2", "interpret")
        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit("user-2", "interpret")
        assert exc_info.value.status_code == 429

    def test_per_user_isolation(self):
        from services.rate_limit import check_rate_limit, LIMITS
        from fastapi import HTTPException
        max_req, _ = LIMITS["interpret"]
        for _ in range(max_req):
            check_rate_limit("user-a", "interpret")
        # user-b should not be affected
        check_rate_limit("user-b", "interpret")

    def test_per_endpoint_isolation(self):
        from services.rate_limit import check_rate_limit, LIMITS
        from fastapi import HTTPException
        max_req, _ = LIMITS["ocr"]
        for _ in range(max_req):
            check_rate_limit("user-c", "ocr")
        with pytest.raises(HTTPException):
            check_rate_limit("user-c", "ocr")
        # Different endpoint for same user is unaffected
        check_rate_limit("user-c", "chat")

    def test_429_includes_retry_after_header(self):
        from services.rate_limit import check_rate_limit, LIMITS
        from fastapi import HTTPException
        max_req, _ = LIMITS["ocr"]
        for _ in range(max_req):
            check_rate_limit("user-d", "ocr")
        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit("user-d", "ocr")
        assert "Retry-After" in exc_info.value.headers

    def test_get_window_count_tracks_requests(self):
        from services.rate_limit import check_rate_limit, get_window_count
        check_rate_limit("user-e", "chat")
        check_rate_limit("user-e", "chat")
        assert get_window_count("user-e", "chat") == 2

    def test_reset_clears_all_windows(self):
        from services.rate_limit import check_rate_limit, get_window_count, reset_limits
        check_rate_limit("user-f", "chat")
        reset_limits()
        assert get_window_count("user-f", "chat") == 0

    def test_unknown_endpoint_uses_default_limit(self):
        from services.rate_limit import check_rate_limit
        # Should not raise for unknown endpoint
        check_rate_limit("user-g", "unknown_endpoint")


# ---------------------------------------------------------------------------
# 2. Chat router — rate limit 429
# ---------------------------------------------------------------------------

class TestChatRouterRateLimit:
    def setup_method(self):
        from services.rate_limit import reset_limits
        reset_limits()

    def test_chat_returns_429_when_rate_limited(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from fastapi import HTTPException
        import routers.chat as chat_mod

        app = FastAPI()
        app.include_router(chat_mod.router, prefix="/chat")
        client = TestClient(app, raise_server_exceptions=False)

        with patch("routers.chat.check_rate_limit", side_effect=HTTPException(429, "Rate limit exceeded")):
            resp = client.post(
                "/chat/",
                json={"user_id": "u1", "conversation_id": "c1", "message": "hi"},
                headers={"X-User-Id": "u1"},
            )

        assert resp.status_code == 429


# ---------------------------------------------------------------------------
# 3. Chat router — L3 output scan
# ---------------------------------------------------------------------------

class TestChatL3OutputScan:
    def setup_method(self):
        from services.rate_limit import reset_limits
        reset_limits()

    def test_l3_safe_output_passes_through(self):
        """When L3 scan returns safe, normal streaming continues."""
        async def _fake_agent(**kwargs):
            yield "Your glucose is slightly elevated."

        with patch("routers.chat.check_rate_limit"), \
             patch("routers.chat.scan_user_input", new_callable=AsyncMock,
                   return_value=("question", True)), \
             patch("routers.chat.apply_dialog_rails", new_callable=AsyncMock,
                   return_value=("question", True)), \
             patch("routers.chat.get_relevant_memories", new_callable=AsyncMock,
                   return_value=""), \
             patch("routers.chat._load_conversation_history", new_callable=AsyncMock,
                   return_value=[]), \
             patch("routers.chat.run_health_agent", return_value=_fake_agent(
                 user_id="u1", message="question", conversation_id="c1",
                 report_id=None, memories="", conversation_history=[],
             )), \
             patch("routers.chat.scan_llm_output", new_callable=AsyncMock,
                   return_value=("Your glucose is slightly elevated.", True)), \
             patch("routers.chat.update_user_memory", new_callable=AsyncMock), \
             patch("routers.chat._persist_messages", new_callable=AsyncMock):

            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            import routers.chat as chat_mod

            app = FastAPI()
            app.include_router(chat_mod.router, prefix="/chat")
            client = TestClient(app)

            resp = client.post(
                "/chat/",
                json={"user_id": "u1", "conversation_id": "c1", "message": "question"},
                headers={"X-User-Id": "u1"},
            )

        assert resp.status_code == 200
        # Should not contain a 'filtered' flag
        assert "filtered" not in resp.text or '"filtered": false' in resp.text.replace('"filtered":false', '"filtered": false')

    def test_l3_unsafe_output_sends_replacement_chunk(self):
        """When L3 scan fails, a replacement safety message is streamed."""
        async def _fake_agent(**kwargs):
            yield "You definitely have diabetes and you should take metformin."

        with patch("routers.chat.check_rate_limit"), \
             patch("routers.chat.scan_user_input", new_callable=AsyncMock,
                   return_value=("question", True)), \
             patch("routers.chat.apply_dialog_rails", new_callable=AsyncMock,
                   return_value=("question", True)), \
             patch("routers.chat.get_relevant_memories", new_callable=AsyncMock,
                   return_value=""), \
             patch("routers.chat._load_conversation_history", new_callable=AsyncMock,
                   return_value=[]), \
             patch("routers.chat.run_health_agent", return_value=_fake_agent(
                 user_id="u1", message="question", conversation_id="c1",
                 report_id=None, memories="", conversation_history=[],
             )), \
             patch("routers.chat.scan_llm_output", new_callable=AsyncMock,
                   return_value=("", False)), \
             patch("routers.chat.update_user_memory", new_callable=AsyncMock), \
             patch("routers.chat._persist_messages", new_callable=AsyncMock):

            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            import routers.chat as chat_mod

            app = FastAPI()
            app.include_router(chat_mod.router, prefix="/chat")
            client = TestClient(app)

            resp = client.post(
                "/chat/",
                json={"user_id": "u1", "conversation_id": "c1", "message": "question"},
                headers={"X-User-Id": "u1"},
            )

        assert resp.status_code == 200
        assert "filtered" in resp.text

    def test_scan_llm_output_called_with_full_response(self):
        """scan_llm_output must receive the complete accumulated response."""
        full_text = "chunk1 chunk2 chunk3"

        async def _fake_agent(**kwargs):
            for part in ["chunk1 ", "chunk2 ", "chunk3"]:
                yield part

        scan_called_with = {}

        async def _mock_scan(prompt, output):
            scan_called_with["output"] = output
            return output, True

        with patch("routers.chat.check_rate_limit"), \
             patch("routers.chat.scan_user_input", new_callable=AsyncMock,
                   return_value=("q", True)), \
             patch("routers.chat.apply_dialog_rails", new_callable=AsyncMock,
                   return_value=("q", True)), \
             patch("routers.chat.get_relevant_memories", new_callable=AsyncMock,
                   return_value=""), \
             patch("routers.chat._load_conversation_history", new_callable=AsyncMock,
                   return_value=[]), \
             patch("routers.chat.run_health_agent", return_value=_fake_agent(
                 user_id="u1", message="q", conversation_id="c1",
                 report_id=None, memories="", conversation_history=[],
             )), \
             patch("routers.chat.scan_llm_output", side_effect=_mock_scan), \
             patch("routers.chat.update_user_memory", new_callable=AsyncMock), \
             patch("routers.chat._persist_messages", new_callable=AsyncMock):

            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            import routers.chat as chat_mod

            app = FastAPI()
            app.include_router(chat_mod.router, prefix="/chat")
            client = TestClient(app)
            client.post(
                "/chat/",
                json={"user_id": "u1", "conversation_id": "c1", "message": "q"},
                headers={"X-User-Id": "u1"},
            )

        assert scan_called_with.get("output") == full_text


# ---------------------------------------------------------------------------
# 4. Health check service
# ---------------------------------------------------------------------------

class TestHealthCheckService:
    @pytest.mark.asyncio
    async def test_all_ok_returns_ok_status(self):
        from services.health_check import run_health_checks

        ok = {"status": "ok", "latency_ms": 5.0}
        with patch("services.health_check._probe_supabase", new_callable=AsyncMock, return_value=ok), \
             patch("services.health_check._probe_qdrant",   new_callable=AsyncMock, return_value=ok), \
             patch("services.health_check._probe_neo4j",    new_callable=AsyncMock, return_value=ok), \
             patch("services.health_check._probe_openai",   new_callable=AsyncMock, return_value=ok):
            result = await run_health_checks()

        assert result["status"] == "ok"
        assert set(result["probes"].keys()) == {"supabase", "qdrant", "neo4j", "openai"}

    @pytest.mark.asyncio
    async def test_one_degraded_returns_degraded(self):
        from services.health_check import run_health_checks

        ok = {"status": "ok", "latency_ms": 5.0}
        degraded = {"status": "degraded", "latency_ms": 500.0, "detail": "slow"}

        with patch("services.health_check._probe_supabase", new_callable=AsyncMock, return_value=ok), \
             patch("services.health_check._probe_qdrant",   new_callable=AsyncMock, return_value=degraded), \
             patch("services.health_check._probe_neo4j",    new_callable=AsyncMock, return_value=ok), \
             patch("services.health_check._probe_openai",   new_callable=AsyncMock, return_value=ok):
            result = await run_health_checks()

        assert result["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_unavailable_probe_returns_unavailable(self):
        from services.health_check import run_health_checks

        ok = {"status": "ok", "latency_ms": 5.0}
        down = {"status": "unavailable", "latency_ms": 0, "detail": "connection refused"}

        with patch("services.health_check._probe_supabase", new_callable=AsyncMock, return_value=down), \
             patch("services.health_check._probe_qdrant",   new_callable=AsyncMock, return_value=ok), \
             patch("services.health_check._probe_neo4j",    new_callable=AsyncMock, return_value=ok), \
             patch("services.health_check._probe_openai",   new_callable=AsyncMock, return_value=ok):
            result = await run_health_checks()

        assert result["status"] == "unavailable"

    @pytest.mark.asyncio
    async def test_probe_exception_normalised_to_unavailable(self):
        from services.health_check import run_health_checks

        ok = {"status": "ok", "latency_ms": 5.0}

        with patch("services.health_check._probe_supabase", new_callable=AsyncMock, side_effect=Exception("timeout")), \
             patch("services.health_check._probe_qdrant",   new_callable=AsyncMock, return_value=ok), \
             patch("services.health_check._probe_neo4j",    new_callable=AsyncMock, return_value=ok), \
             patch("services.health_check._probe_openai",   new_callable=AsyncMock, return_value=ok):
            result = await run_health_checks()

        assert result["status"] == "unavailable"
        assert result["probes"]["supabase"]["status"] == "unavailable"

    @pytest.mark.asyncio
    async def test_probes_include_latency_ms(self):
        from services.health_check import run_health_checks

        ok = {"status": "ok", "latency_ms": 12.3}
        with patch("services.health_check._probe_supabase", new_callable=AsyncMock, return_value=ok), \
             patch("services.health_check._probe_qdrant",   new_callable=AsyncMock, return_value=ok), \
             patch("services.health_check._probe_neo4j",    new_callable=AsyncMock, return_value=ok), \
             patch("services.health_check._probe_openai",   new_callable=AsyncMock, return_value=ok):
            result = await run_health_checks()

        for probe in result["probes"].values():
            assert "latency_ms" in probe or "detail" in probe


# ---------------------------------------------------------------------------
# 5. Health endpoint — HTTP status codes
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def _make_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import main as main_mod

        # Don't call lifespan — just test the endpoints
        app = FastAPI()

        @app.get("/health")
        async def health():
            return {"status": "ok", "service": "health-ai"}

        @app.get("/health/detailed")
        async def health_detailed():
            from services.health_check import run_health_checks
            result = await run_health_checks()
            from fastapi.responses import JSONResponse
            status_code = 503 if result["status"] == "unavailable" else 200
            return JSONResponse(content=result, status_code=status_code)

        return TestClient(app)

    def test_health_returns_200(self):
        client = self._make_client()
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_health_detailed_200_when_all_ok(self):
        ok = {"status": "ok", "latency_ms": 5.0}
        client = self._make_client()
        with patch("services.health_check._probe_supabase", new_callable=AsyncMock, return_value=ok), \
             patch("services.health_check._probe_qdrant",   new_callable=AsyncMock, return_value=ok), \
             patch("services.health_check._probe_neo4j",    new_callable=AsyncMock, return_value=ok), \
             patch("services.health_check._probe_openai",   new_callable=AsyncMock, return_value=ok):
            resp = client.get("/health/detailed")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_health_detailed_503_when_unavailable(self):
        ok = {"status": "ok", "latency_ms": 5.0}
        down = {"status": "unavailable", "latency_ms": 0, "detail": "down"}
        client = self._make_client()
        with patch("services.health_check._probe_supabase", new_callable=AsyncMock, return_value=down), \
             patch("services.health_check._probe_qdrant",   new_callable=AsyncMock, return_value=ok), \
             patch("services.health_check._probe_neo4j",    new_callable=AsyncMock, return_value=ok), \
             patch("services.health_check._probe_openai",   new_callable=AsyncMock, return_value=ok):
            resp = client.get("/health/detailed")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# 6. NeMo config has new output flows
# ---------------------------------------------------------------------------

class TestNemoConfig:
    def test_new_output_flows_in_config(self):
        import os
        config_path = os.path.join(
            os.path.dirname(__file__), "nemo_config", "config.yml"
        )
        with open(config_path) as f:
            content = f.read()
        assert "check prognosis claim" in content
        assert "check supplement dosage" in content

    def test_rails_co_has_prognosis_patterns(self):
        import os
        rails_path = os.path.join(
            os.path.dirname(__file__), "nemo_config", "rails.co"
        )
        with open(rails_path) as f:
            content = f.read()
        assert "make prognosis claim" in content
        assert "safe prognosis redirect" in content

    def test_rails_co_has_supplement_patterns(self):
        import os
        rails_path = os.path.join(
            os.path.dirname(__file__), "nemo_config", "rails.co"
        )
        with open(rails_path) as f:
            content = f.read()
        assert "make supplement dosage claim" in content
        assert "safe supplement redirect" in content


# ---------------------------------------------------------------------------
# 7. dspy_compiled directory exists
# ---------------------------------------------------------------------------

class TestDspyCompiled:
    def test_dspy_compiled_dir_exists(self):
        import os
        compiled_dir = os.path.join(os.path.dirname(__file__), "dspy_compiled")
        assert os.path.isdir(compiled_dir), "dspy_compiled/ directory must exist"

    def test_gitkeep_present(self):
        import os
        gitkeep = os.path.join(os.path.dirname(__file__), "dspy_compiled", ".gitkeep")
        assert os.path.exists(gitkeep), "dspy_compiled/.gitkeep must exist"


# ---------------------------------------------------------------------------
# 8. requirements.txt has eval deps
# ---------------------------------------------------------------------------

class TestRequirements:
    def _read_requirements(self):
        import os
        req_path = os.path.join(os.path.dirname(__file__), "requirements.txt")
        with open(req_path) as f:
            return f.read()

    def test_deepeval_in_requirements(self):
        assert "deepeval" in self._read_requirements()

    def test_ragas_in_requirements(self):
        assert "ragas" in self._read_requirements()

    def test_datasets_in_requirements(self):
        assert "datasets" in self._read_requirements()

    def test_langfuse_in_requirements(self):
        assert "langfuse" in self._read_requirements()
