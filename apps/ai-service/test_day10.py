"""
Day 10 tests — Mem0 multi-scope memory
  - mem0_recall: structured results, scope query augmentation, graceful degradation
  - store_clinical_memory: calls mem0.add with clinical metadata
  - update_user_memory: passes metadata kwarg through
  - mem0_recall tool: formats output, scope parameter, no-results message
  - get_tools: mem0_recall registered (8 tools total)
  - chat router: _load_conversation_history, _persist_messages
  - agents/health_agent: conversation_history prepended to messages
  - OCR: _store_clinical_memory_from_labs builds correct summary
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════

def _make_mem0_results(memories: list[str]) -> dict:
    return {
        "results": [{"memory": m, "score": 0.85, "metadata": {}} for m in memories]
    }


# ══════════════════════════════════════════════════════════════════════
# 1. mem0_recall (service function)
# ══════════════════════════════════════════════════════════════════════

class TestMem0RecallFunction:
    async def test_returns_empty_when_not_initialized(self):
        import services.memory as mem_module
        original = mem_module._mem0
        mem_module._mem0 = None
        try:
            from services.memory import mem0_recall
            result = await mem0_recall("user-1", "HbA1c history")
        finally:
            mem_module._mem0 = original
        assert result == []

    async def test_returns_structured_list(self):
        import services.memory as mem_module
        mock_mem0 = MagicMock()
        mock_mem0.search.return_value = _make_mem0_results(["HbA1c was 7.2% in Jan 2024"])
        original = mem_module._mem0
        mem_module._mem0 = mock_mem0
        try:
            from services.memory import mem0_recall
            results = await mem0_recall("user-1", "HbA1c")
        finally:
            mem_module._mem0 = original

        assert len(results) == 1
        assert results[0]["memory"] == "HbA1c was 7.2% in Jan 2024"
        assert results[0]["score"] == pytest.approx(0.85)

    async def test_scope_prefix_added_to_query(self):
        import services.memory as mem_module
        mock_mem0 = MagicMock()
        mock_mem0.search.return_value = {"results": []}
        original = mem_module._mem0
        mem_module._mem0 = mock_mem0
        try:
            from services.memory import mem0_recall
            await mem0_recall("user-1", "cholesterol", scope="clinical")
        finally:
            mem_module._mem0 = original

        called_query = mock_mem0.search.call_args[0][0]
        assert called_query == "[clinical] cholesterol"

    async def test_no_scope_passes_query_unchanged(self):
        import services.memory as mem_module
        mock_mem0 = MagicMock()
        mock_mem0.search.return_value = {"results": []}
        original = mem_module._mem0
        mem_module._mem0 = mock_mem0
        try:
            from services.memory import mem0_recall
            await mem0_recall("user-1", "diet preferences")
        finally:
            mem_module._mem0 = original

        called_query = mock_mem0.search.call_args[0][0]
        assert called_query == "diet preferences"

    async def test_skips_empty_memory_entries(self):
        import services.memory as mem_module
        mock_mem0 = MagicMock()
        mock_mem0.search.return_value = {
            "results": [
                {"memory": "Real memory", "score": 0.9, "metadata": {}},
                {"memory": "",            "score": 0.5, "metadata": {}},  # empty — should be skipped
                {"memory": None,          "score": 0.4, "metadata": {}},  # None — should be skipped
            ]
        }
        original = mem_module._mem0
        mem_module._mem0 = mock_mem0
        try:
            from services.memory import mem0_recall
            results = await mem0_recall("user-1", "anything")
        finally:
            mem_module._mem0 = original

        assert len(results) == 1
        assert results[0]["memory"] == "Real memory"

    async def test_exception_returns_empty(self):
        import services.memory as mem_module
        mock_mem0 = MagicMock()
        mock_mem0.search.side_effect = Exception("Qdrant unavailable")
        original = mem_module._mem0
        mem_module._mem0 = mock_mem0
        try:
            from services.memory import mem0_recall
            result = await mem0_recall("user-1", "anything")
        finally:
            mem_module._mem0 = original

        assert result == []

    async def test_passes_limit_to_search(self):
        import services.memory as mem_module
        mock_mem0 = MagicMock()
        mock_mem0.search.return_value = {"results": []}
        original = mem_module._mem0
        mem_module._mem0 = mock_mem0
        try:
            from services.memory import mem0_recall
            await mem0_recall("user-1", "test", limit=3)
        finally:
            mem_module._mem0 = original

        assert mock_mem0.search.call_args[1]["limit"] == 3


# ══════════════════════════════════════════════════════════════════════
# 2. store_clinical_memory
# ══════════════════════════════════════════════════════════════════════

class TestStoreClinicalMemory:
    async def test_noop_when_not_initialized(self):
        import services.memory as mem_module
        original = mem_module._mem0
        mem_module._mem0 = None
        try:
            from services.memory import store_clinical_memory
            # Should not raise
            await store_clinical_memory("user-1", "HbA1c 7.2%")
        finally:
            mem_module._mem0 = original

    async def test_calls_add_with_clinical_metadata(self):
        import services.memory as mem_module
        mock_mem0 = MagicMock()
        original = mem_module._mem0
        mem_module._mem0 = mock_mem0
        try:
            from services.memory import store_clinical_memory
            await store_clinical_memory("user-1", "Lab: HbA1c 7.2% [high]")
        finally:
            mem_module._mem0 = original

        mock_mem0.add.assert_called_once()
        call_kwargs = mock_mem0.add.call_args[1]
        assert call_kwargs["user_id"] == "user-1"
        assert call_kwargs["metadata"] == {"type": "clinical"}
        messages = mock_mem0.add.call_args[0][0]
        assert any("HbA1c" in m.get("content", "") for m in messages)

    async def test_message_role_is_system(self):
        import services.memory as mem_module
        mock_mem0 = MagicMock()
        original = mem_module._mem0
        mem_module._mem0 = mock_mem0
        try:
            from services.memory import store_clinical_memory
            await store_clinical_memory("u", "clinical text")
        finally:
            mem_module._mem0 = original

        messages = mock_mem0.add.call_args[0][0]
        assert messages[0]["role"] == "system"

    async def test_exception_does_not_raise(self):
        import services.memory as mem_module
        mock_mem0 = MagicMock()
        mock_mem0.add.side_effect = Exception("connection failed")
        original = mem_module._mem0
        mem_module._mem0 = mock_mem0
        try:
            from services.memory import store_clinical_memory
            await store_clinical_memory("u", "text")
        finally:
            mem_module._mem0 = original


# ══════════════════════════════════════════════════════════════════════
# 3. update_user_memory — metadata kwarg
# ══════════════════════════════════════════════════════════════════════

class TestUpdateUserMemory:
    async def test_passes_metadata_to_add(self):
        import services.memory as mem_module
        mock_mem0 = MagicMock()
        original = mem_module._mem0
        mem_module._mem0 = mock_mem0
        try:
            from services.memory import update_user_memory
            await update_user_memory(
                "user-1",
                [{"role": "user", "content": "I prefer vegetarian food"}],
                metadata={"type": "preference"},
            )
        finally:
            mem_module._mem0 = original

        call_kwargs = mock_mem0.add.call_args[1]
        assert call_kwargs["metadata"] == {"type": "preference"}

    async def test_no_metadata_defaults_to_none(self):
        import services.memory as mem_module
        mock_mem0 = MagicMock()
        original = mem_module._mem0
        mem_module._mem0 = mock_mem0
        try:
            from services.memory import update_user_memory
            await update_user_memory("user-1", [{"role": "user", "content": "hello"}])
        finally:
            mem_module._mem0 = original

        call_kwargs = mock_mem0.add.call_args[1]
        assert call_kwargs["metadata"] is None


# ══════════════════════════════════════════════════════════════════════
# 4. mem0_recall LangGraph tool
# ══════════════════════════════════════════════════════════════════════

class TestMem0RecallTool:
    async def test_formats_results_as_bullets(self):
        from agents.tools import mem0_recall as tool
        mock_results = [
            {"memory": "User prefers vegetarian diet", "score": 0.92, "metadata": {"type": "preference"}},
            {"memory": "User has HbA1c 7.2%", "score": 0.88, "metadata": {"type": "clinical"}},
        ]
        with patch("services.memory.mem0_recall", new=AsyncMock(return_value=mock_results)):
            result = await tool.ainvoke({"user_id": "user-1", "query": "diet", "scope": "preference"})

        assert "vegetarian diet" in result
        assert "HbA1c" in result
        assert result.startswith("•")

    async def test_no_results_returns_message(self):
        from agents.tools import mem0_recall as tool
        with patch("services.memory.mem0_recall", new=AsyncMock(return_value=[])):
            result = await tool.ainvoke({"user_id": "u", "query": "nothing"})

        assert "No relevant memories" in result

    async def test_scope_none_allowed(self):
        from agents.tools import mem0_recall as tool
        with patch("services.memory.mem0_recall", new=AsyncMock(return_value=[])) as mock_recall:
            await tool.ainvoke({"user_id": "u", "query": "anything"})
        # scope defaults to None
        mock_recall.assert_called_once_with("u", "anything", scope=None)

    async def test_scope_clinical_passed_through(self):
        from agents.tools import mem0_recall as tool
        with patch("services.memory.mem0_recall", new=AsyncMock(return_value=[])) as mock_recall:
            await tool.ainvoke({"user_id": "u", "query": "labs", "scope": "clinical"})
        mock_recall.assert_called_once_with("u", "labs", scope="clinical")

    async def test_registered_in_get_tools(self):
        from agents.tools import get_tools
        tool_names = [t.name for t in get_tools()]
        assert "mem0_recall" in tool_names

    async def test_8_tools_total(self):
        from agents.tools import get_tools
        assert len(get_tools()) == 8


# ══════════════════════════════════════════════════════════════════════
# 5. Chat router — session continuity helpers
# ══════════════════════════════════════════════════════════════════════

class TestChatHelpers:
    def _make_db_chain(self, rows: list[dict]):
        result = MagicMock()
        result.data = rows
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.limit.return_value = chain
        chain.insert.return_value = chain
        chain.execute = AsyncMock(return_value=result)
        db = MagicMock()
        db.table.return_value = chain
        return db, chain

    async def test_load_conversation_history_returns_chronological_messages(self):
        from routers.chat import _load_conversation_history
        # DB returns newest-first (desc order); function reverses to chronological
        rows = [
            {"role": "assistant", "content": "Hi there"},   # newer — returned first by desc query
            {"role": "user",      "content": "Hello"},      # older — returned second
        ]
        db, _ = self._make_db_chain(rows)
        with patch("routers.chat.get_supabase", return_value=db):
            history = await _load_conversation_history("conv-1")

        assert len(history) == 2
        # After reversal: chronological order
        assert history[0] == {"role": "user",      "content": "Hello"}
        assert history[1] == {"role": "assistant", "content": "Hi there"}

    async def test_load_conversation_history_reverses_desc_order(self):
        """We fetch desc (newest first), then reverse to get chronological."""
        from routers.chat import _load_conversation_history
        # Simulate DB returning newest-first order
        rows = [
            {"role": "assistant", "content": "Second"},
            {"role": "user",      "content": "First"},
        ]
        db, chain = self._make_db_chain(rows)
        with patch("routers.chat.get_supabase", return_value=db):
            history = await _load_conversation_history("conv-1")

        # Should be reversed to chronological
        assert history[0]["content"] == "First"
        assert history[1]["content"] == "Second"

    async def test_load_conversation_history_empty_on_error(self):
        from routers.chat import _load_conversation_history
        with patch("routers.chat.get_supabase", side_effect=Exception("DB down")):
            history = await _load_conversation_history("conv-1")

        assert history == []

    async def test_load_conversation_history_empty_for_new_conversation(self):
        from routers.chat import _load_conversation_history
        db, _ = self._make_db_chain([])
        with patch("routers.chat.get_supabase", return_value=db):
            history = await _load_conversation_history("new-conv")

        assert history == []

    async def test_persist_messages_inserts_both_roles(self):
        from routers.chat import _persist_messages
        db, chain = self._make_db_chain([])
        with patch("routers.chat.get_supabase", return_value=db):
            await _persist_messages(
                "conv-1", "user-1",
                [
                    {"role": "user",      "content": "What is my HbA1c?"},
                    {"role": "assistant", "content": "Your HbA1c is 7.2%."},
                ]
            )

        inserted = chain.insert.call_args[0][0]
        roles = [r["role"] for r in inserted]
        assert "user" in roles
        assert "assistant" in roles
        assert all(r["conversation_id"] == "conv-1" for r in inserted)
        assert all(r["user_id"] == "user-1" for r in inserted)

    async def test_persist_messages_error_does_not_raise(self):
        from routers.chat import _persist_messages
        with patch("routers.chat.get_supabase", side_effect=Exception("DB error")):
            # Must not raise
            await _persist_messages("c", "u", [{"role": "user", "content": "hi"}])


# ══════════════════════════════════════════════════════════════════════
# 6. Health agent — conversation_history in initial state
# ══════════════════════════════════════════════════════════════════════

class TestHealthAgentHistory:
    async def test_conversation_history_prepended_to_messages(self):
        """Prior messages must appear before the current user message in state."""
        prior = [
            {"role": "user",      "content": "What is HbA1c?"},
            {"role": "assistant", "content": "HbA1c measures average blood sugar."},
        ]
        captured_state: dict = {}

        async def _fake_stream(initial_state, version, config=None):
            captured_state.update(initial_state)
            return
            yield  # make it an async generator

        mock_graph = MagicMock()
        mock_graph.astream_events = _fake_stream

        with patch("agents.health_agent.get_graph", return_value=mock_graph), \
             patch("agents.health_agent.get_langfuse_callback", return_value=None):
            from agents.health_agent import run_health_agent
            gen = run_health_agent(
                user_id="u", message="Follow-up question",
                conversation_id="c", report_id=None,
                memories="", conversation_history=prior,
            )
            async for _ in gen:
                pass

        messages = captured_state["messages"]
        assert messages[0] == {"role": "user",      "content": "What is HbA1c?"}
        assert messages[1] == {"role": "assistant", "content": "HbA1c measures average blood sugar."}
        assert messages[2] == {"role": "user",      "content": "Follow-up question"}

    async def test_no_history_uses_only_current_message(self):
        captured_state: dict = {}

        async def _fake_stream(initial_state, version, config=None):
            captured_state.update(initial_state)
            return
            yield

        mock_graph = MagicMock()
        mock_graph.astream_events = _fake_stream

        with patch("agents.health_agent.get_graph", return_value=mock_graph), \
             patch("agents.health_agent.get_langfuse_callback", return_value=None):
            from agents.health_agent import run_health_agent
            gen = run_health_agent(
                user_id="u", message="First message",
                conversation_id="c", report_id=None,
                memories="", conversation_history=None,
            )
            async for _ in gen:
                pass

        assert len(captured_state["messages"]) == 1
        assert captured_state["messages"][0]["content"] == "First message"


# ══════════════════════════════════════════════════════════════════════
# 7. OCR — _store_clinical_memory_from_labs
# ══════════════════════════════════════════════════════════════════════

class TestOCRClinicalMemory:
    async def test_builds_summary_with_biomarker_values(self):
        from services.ocr import _store_clinical_memory_from_labs
        events = [
            {
                "biomarker_name": "HbA1c", "biomarker_code": "4548-4",
                "value_numeric": 7.2, "unit": "%", "status": "high",
            },
            {
                "biomarker_name": "Creatinine", "biomarker_code": "2160-0",
                "value_numeric": 1.1, "unit": "mg/dL", "status": "normal",
            },
        ]
        mock_store = AsyncMock()
        with patch("services.memory.store_clinical_memory", mock_store):
            await _store_clinical_memory_from_labs("user-1", events, "2024-06-15")

        mock_store.assert_called_once()
        text = mock_store.call_args[0][1]
        assert "2024-06-15" in text
        assert "HbA1c" in text
        assert "7.2" in text
        assert "Creatinine" in text

    async def test_skips_events_without_numeric_value(self):
        from services.ocr import _store_clinical_memory_from_labs
        events = [
            {"biomarker_name": "Test", "value_numeric": None, "unit": "", "status": "unknown"},
        ]
        mock_store = AsyncMock()
        with patch("services.memory.store_clinical_memory", mock_store):
            await _store_clinical_memory_from_labs("user-1", events, "2024-06-15")

        # Only header row — no actual values — should not call store
        mock_store.assert_not_called()

    async def test_empty_events_does_not_call_store(self):
        from services.ocr import _store_clinical_memory_from_labs
        mock_store = AsyncMock()
        with patch("services.memory.store_clinical_memory", mock_store):
            await _store_clinical_memory_from_labs("user-1", [], "2024-06-15")

        mock_store.assert_not_called()

    async def test_includes_lab_date_in_summary(self):
        from services.ocr import _store_clinical_memory_from_labs
        events = [{"biomarker_name": "Glucose", "value_numeric": 105.0, "unit": "mg/dL", "status": "normal"}]
        mock_store = AsyncMock()
        with patch("services.memory.store_clinical_memory", mock_store):
            await _store_clinical_memory_from_labs("user-1", events, "2024-03-22")

        text = mock_store.call_args[0][1]
        assert "2024-03-22" in text
