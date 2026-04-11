"""
Day 9 tests — Graphiti bi-temporal KG integration
  - query_graph_context: returns facts + episodes, graceful degradation when not init'd
  - store_health_episode: correct episode body format, temporal reference_time
  - extract_and_store_facts: episode body from interpretation dict
  - retrieve_graph_context tool: formats results with temporal annotations
  - OCR wiring: _store_lab_episodes fires asyncio task after DB insert
  - Wearable wiring: _store_wearable_episodes groups by day/biomarker, caps at 200
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ══════════════════════════════════════════════════════════════════════
# Fixtures / helpers
# ══════════════════════════════════════════════════════════════════════

def _make_edge(fact: str, valid_at=None, invalid_at=None):
    edge = MagicMock()
    edge.fact = fact
    edge.valid_at = valid_at
    edge.invalid_at = invalid_at
    return edge


def _make_episode(content: str, valid_at=None):
    ep = MagicMock()
    ep.content = content
    ep.valid_at = valid_at
    return ep


def _make_search_results(edges=(), episodes=()):
    sr = MagicMock()
    sr.edges = list(edges)
    sr.episodes = list(episodes)
    return sr


# ══════════════════════════════════════════════════════════════════════
# 1. query_graph_context
# ══════════════════════════════════════════════════════════════════════

class TestQueryGraphContext:
    async def test_returns_empty_when_not_initialized(self):
        import services.memory as mem_module
        original = mem_module._graphiti
        mem_module._graphiti = None
        try:
            from services.memory import query_graph_context
            result = await query_graph_context("user-1", "HbA1c trend")
        finally:
            mem_module._graphiti = original
        assert result == []

    async def test_returns_facts_from_edges(self):
        import services.memory as mem_module
        mock_graphiti = AsyncMock()
        edge = _make_edge(
            "Patient HbA1c was 7.2% in January 2024",
            valid_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
        )
        mock_graphiti.search_.return_value = _make_search_results(edges=[edge])
        original = mem_module._graphiti
        mem_module._graphiti = mock_graphiti
        try:
            from services.memory import query_graph_context
            results = await query_graph_context("user-1", "HbA1c")
        finally:
            mem_module._graphiti = original

        assert len(results) == 1
        assert results[0]["type"] == "fact"
        assert "HbA1c" in results[0]["content"]
        assert results[0]["valid_at"] == "2024-01-15T00:00:00+00:00"
        assert results[0]["invalid_at"] is None

    async def test_returns_episodes(self):
        import services.memory as mem_module
        mock_graphiti = AsyncMock()
        ep = _make_episode(
            "Heart rate: 72 bpm on 2024-06-15",
            valid_at=datetime(2024, 6, 15, tzinfo=timezone.utc),
        )
        mock_graphiti.search_.return_value = _make_search_results(episodes=[ep])
        original = mem_module._graphiti
        mem_module._graphiti = mock_graphiti
        try:
            from services.memory import query_graph_context
            results = await query_graph_context("user-1", "heart rate")
        finally:
            mem_module._graphiti = original

        assert len(results) == 1
        assert results[0]["type"] == "episode"
        assert "Heart rate" in results[0]["content"]
        assert results[0]["valid_at"] is not None

    async def test_returns_both_edges_and_episodes(self):
        import services.memory as mem_module
        mock_graphiti = AsyncMock()
        mock_graphiti.search_.return_value = _make_search_results(
            edges=[_make_edge("fact 1"), _make_edge("fact 2")],
            episodes=[_make_episode("episode 1")],
        )
        original = mem_module._graphiti
        mem_module._graphiti = mock_graphiti
        try:
            from services.memory import query_graph_context
            results = await query_graph_context("user-1", "anything")
        finally:
            mem_module._graphiti = original

        assert len(results) == 3
        types = [r["type"] for r in results]
        assert types.count("fact") == 2
        assert types.count("episode") == 1

    async def test_invalid_at_populated_for_superseded_facts(self):
        import services.memory as mem_module
        mock_graphiti = AsyncMock()
        edge = _make_edge(
            "Patient weight was 85 kg",
            valid_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            invalid_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        mock_graphiti.search_.return_value = _make_search_results(edges=[edge])
        original = mem_module._graphiti
        mem_module._graphiti = mock_graphiti
        try:
            from services.memory import query_graph_context
            results = await query_graph_context("user-1", "weight")
        finally:
            mem_module._graphiti = original

        assert results[0]["invalid_at"] == "2024-06-01T00:00:00+00:00"

    async def test_passes_group_id_and_limit(self):
        import services.memory as mem_module
        mock_graphiti = AsyncMock()
        mock_graphiti.search_.return_value = _make_search_results()
        original = mem_module._graphiti
        mem_module._graphiti = mock_graphiti
        try:
            from services.memory import query_graph_context
            from graphiti_core.search.search_config import SearchConfig
            await query_graph_context("user-42", "cholesterol", num_results=7)
        finally:
            mem_module._graphiti = original

        call_kwargs = mock_graphiti.search_.call_args[1]
        assert call_kwargs["group_ids"] == ["user-42"]
        assert call_kwargs["config"].limit == 7

    async def test_exception_returns_empty_not_raises(self):
        import services.memory as mem_module
        mock_graphiti = AsyncMock()
        mock_graphiti.search_.side_effect = Exception("Neo4j connection refused")
        original = mem_module._graphiti
        mem_module._graphiti = mock_graphiti
        try:
            from services.memory import query_graph_context
            result = await query_graph_context("user-1", "anything")
        finally:
            mem_module._graphiti = original

        assert result == []


# ══════════════════════════════════════════════════════════════════════
# 2. store_health_episode
# ══════════════════════════════════════════════════════════════════════

class TestStoreHealthEpisode:
    async def test_noop_when_graphiti_not_initialized(self):
        import services.memory as mem_module
        original = mem_module._graphiti
        mem_module._graphiti = None
        try:
            from services.memory import store_health_episode
            # Should not raise
            await store_health_episode("user-1", {
                "event_type": "heart_rate",
                "occurred_at": "2024-06-15T09:00:00+00:00",
                "biomarker_name": "Heart Rate",
                "biomarker_code": "8867-4",
                "value_numeric": 72.0,
                "unit": "bpm",
                "status": "normal",
                "source": "fitbit",
            })
        finally:
            mem_module._graphiti = original

    async def test_calls_add_episode_with_correct_args(self):
        import services.memory as mem_module
        mock_graphiti = AsyncMock()
        mock_graphiti.add_episode = AsyncMock()
        original = mem_module._graphiti
        mem_module._graphiti = mock_graphiti
        try:
            from services.memory import store_health_episode
            event = {
                "event_type": "lab_result",
                "occurred_at": "2024-06-15T00:00:00+00:00",
                "biomarker_name": "HbA1c",
                "biomarker_code": "4548-4",
                "value_numeric": 7.2,
                "unit": "%",
                "status": "high",
                "source": "lab_report",
            }
            await store_health_episode("user-abc", event)
        finally:
            mem_module._graphiti = original

        mock_graphiti.add_episode.assert_called_once()
        kwargs = mock_graphiti.add_episode.call_args[1]
        assert "user-abc" in kwargs["name"]
        assert kwargs["group_id"] == "user-abc"
        assert "HbA1c" in kwargs["episode_body"]
        assert "7.2" in kwargs["episode_body"]

    async def test_episode_reference_time_from_occurred_at(self):
        import services.memory as mem_module
        mock_graphiti = AsyncMock()
        mock_graphiti.add_episode = AsyncMock()
        original = mem_module._graphiti
        mem_module._graphiti = mock_graphiti
        try:
            from services.memory import store_health_episode
            await store_health_episode("u", {
                "event_type": "lab_result",
                "occurred_at": "2024-03-10T00:00:00+00:00",
                "source": "lab_report",
            })
        finally:
            mem_module._graphiti = original

        kwargs = mock_graphiti.add_episode.call_args[1]
        ref = kwargs["reference_time"]
        assert ref.year == 2024 and ref.month == 3 and ref.day == 10

    async def test_episode_uses_now_when_occurred_at_missing(self):
        import services.memory as mem_module
        mock_graphiti = AsyncMock()
        mock_graphiti.add_episode = AsyncMock()
        original = mem_module._graphiti
        mem_module._graphiti = mock_graphiti
        try:
            from services.memory import store_health_episode
            before = datetime.now(timezone.utc)
            await store_health_episode("u", {"event_type": "activity", "source": "fitbit"})
            after = datetime.now(timezone.utc)
        finally:
            mem_module._graphiti = original

        kwargs = mock_graphiti.add_episode.call_args[1]
        ref = kwargs["reference_time"]
        assert before <= ref <= after

    async def test_exception_in_add_episode_does_not_raise(self):
        import services.memory as mem_module
        mock_graphiti = AsyncMock()
        mock_graphiti.add_episode.side_effect = Exception("Neo4j error")
        original = mem_module._graphiti
        mem_module._graphiti = mock_graphiti
        try:
            from services.memory import store_health_episode
            # Must not raise
            await store_health_episode("u", {
                "event_type": "heart_rate", "occurred_at": "2024-01-01T00:00:00+00:00", "source": "fitbit"
            })
        finally:
            mem_module._graphiti = original


# ══════════════════════════════════════════════════════════════════════
# 3. extract_and_store_facts
# ══════════════════════════════════════════════════════════════════════

class TestExtractAndStoreFacts:
    async def test_noop_when_not_initialized(self):
        import services.memory as mem_module
        original = mem_module._graphiti
        mem_module._graphiti = None
        try:
            from services.memory import extract_and_store_facts
            # Should not raise
            await extract_and_store_facts("user-1", {"key_findings": []}, "report-123")
        finally:
            mem_module._graphiti = original

    async def test_episode_body_includes_findings(self):
        import services.memory as mem_module
        mock_graphiti = AsyncMock()
        mock_graphiti.add_episode = AsyncMock()
        original = mem_module._graphiti
        mem_module._graphiti = mock_graphiti
        try:
            from services.memory import extract_and_store_facts
            interpretation = {
                "key_findings": [
                    {"name": "HbA1c", "loinc": "4548-4", "value": "7.2%", "status": "high", "explanation": "Elevated"},
                    {"name": "Creatinine", "loinc": "2160-0", "value": "1.1 mg/dL", "status": "normal", "explanation": "Normal"},
                ],
                "dietary_suggestions": [
                    {"suggestion": "Reduce refined carbohydrates", "mechanism": "Lower postprandial glucose"},
                ],
            }
            await extract_and_store_facts("user-abc", interpretation, "report-xyz")
        finally:
            mem_module._graphiti = original

        mock_graphiti.add_episode.assert_called_once()
        kwargs = mock_graphiti.add_episode.call_args[1]
        body = kwargs["episode_body"]
        assert "HbA1c" in body
        assert "Creatinine" in body
        assert "Reduce refined carbohydrates" in body
        assert kwargs["group_id"] == "user-abc"
        assert "report-xyz" in kwargs["name"]


# ══════════════════════════════════════════════════════════════════════
# 4. retrieve_graph_context tool
# ══════════════════════════════════════════════════════════════════════

class TestRetrieveGraphContextTool:
    async def test_formats_facts_with_temporal_annotations(self):
        from agents.tools import retrieve_graph_context
        mock_results = [
            {"type": "fact", "content": "HbA1c was 7.2%", "valid_at": "2024-01-15T00:00:00+00:00", "invalid_at": None},
            {"type": "fact", "content": "HbA1c was 6.8%", "valid_at": "2024-06-10T00:00:00+00:00", "invalid_at": None},
        ]
        with patch("services.memory.query_graph_context", new=AsyncMock(return_value=mock_results)):
            result = await retrieve_graph_context.ainvoke({"user_id": "user-1", "query": "HbA1c"})

        assert "HbA1c was 7.2%" in result
        assert "[from 2024-01-15]" in result
        assert "HbA1c was 6.8%" in result

    async def test_shows_invalid_at_for_superseded_fact(self):
        from agents.tools import retrieve_graph_context
        mock_results = [
            {
                "type": "fact",
                "content": "Patient weight was 85 kg",
                "valid_at": "2024-01-01T00:00:00+00:00",
                "invalid_at": "2024-06-01T00:00:00+00:00",
            }
        ]
        with patch("services.memory.query_graph_context", new=AsyncMock(return_value=mock_results)):
            result = await retrieve_graph_context.ainvoke({"user_id": "u", "query": "weight"})

        assert "[from 2024-01-01]" in result
        assert "[until 2024-06-01]" in result

    async def test_no_results_returns_not_found_message(self):
        from agents.tools import retrieve_graph_context
        with patch("services.memory.query_graph_context", new=AsyncMock(return_value=[])):
            result = await retrieve_graph_context.ainvoke({"user_id": "u", "query": "nothing"})

        assert "No relevant facts" in result

    async def test_episodes_formatted_with_valid_at(self):
        from agents.tools import retrieve_graph_context
        mock_results = [
            {"type": "episode", "content": "Resting HR 62 bpm", "valid_at": "2024-05-01T00:00:00+00:00", "invalid_at": None},
        ]
        with patch("services.memory.query_graph_context", new=AsyncMock(return_value=mock_results)):
            result = await retrieve_graph_context.ainvoke({"user_id": "u", "query": "HR"})

        assert "Resting HR 62 bpm" in result
        assert "[from 2024-05-01]" in result

    async def test_tool_is_registered_in_get_tools(self):
        from agents.tools import get_tools
        tool_names = [t.name for t in get_tools()]
        assert "retrieve_graph_context" in tool_names


# ══════════════════════════════════════════════════════════════════════
# 5. OCR wiring — _store_lab_episodes
# ══════════════════════════════════════════════════════════════════════

class TestOCRGraphitiWiring:
    async def test_store_lab_episodes_calls_store_for_each_event(self):
        from services.ocr import _store_lab_episodes
        events = [
            {"user_id": "u", "biomarker_code": "4548-4", "occurred_at": "2024-01-01", "source": "lab_report", "event_type": "lab_result"},
            {"user_id": "u", "biomarker_code": "2160-0", "occurred_at": "2024-01-01", "source": "lab_report", "event_type": "lab_result"},
        ]
        mock_store = AsyncMock()
        with patch("services.memory.store_health_episode", mock_store):
            await _store_lab_episodes("user-1", events)

        assert mock_store.call_count == 2

    async def test_store_lab_episodes_empty_list_is_noop(self):
        from services.ocr import _store_lab_episodes
        mock_store = AsyncMock()
        with patch("services.memory.store_health_episode", mock_store):
            await _store_lab_episodes("user-1", [])
        mock_store.assert_not_called()

    async def test_store_lab_episodes_error_per_event_does_not_abort_others(self):
        from services.ocr import _store_lab_episodes
        events = [
            {"user_id": "u", "biomarker_code": "4548-4", "occurred_at": "2024-01-01", "source": "lab_report", "event_type": "lab_result"},
            {"user_id": "u", "biomarker_code": "2160-0", "occurred_at": "2024-01-01", "source": "lab_report", "event_type": "lab_result"},
        ]
        # First call raises, second should still be called
        mock_store = AsyncMock(side_effect=[Exception("Neo4j down"), None])
        with patch("services.memory.store_health_episode", mock_store):
            await _store_lab_episodes("user-1", events)

        assert mock_store.call_count == 2


# ══════════════════════════════════════════════════════════════════════
# 6. Wearable episode helper — _store_wearable_episodes
# ══════════════════════════════════════════════════════════════════════

class TestStoreWearableEpisodes:
    def _make_events(self, n: int, biomarker: str = "8867-4", date: str = "2024-06-15") -> list[dict]:
        return [
            {
                "user_id": "u",
                "biomarker_code": biomarker,
                "biomarker_name": "Heart Rate",
                "occurred_at": f"{date}T{i:02d}:00:00+00:00",
                "value_numeric": 60.0 + i,
                "unit": "bpm",
                "event_type": "heart_rate",
                "source": "fitbit",
            }
            for i in range(n)
        ]

    async def test_one_episode_per_day_per_biomarker(self):
        from routers.wearables import _store_wearable_episodes
        events = self._make_events(24, date="2024-06-15")  # 24 readings, same day/biomarker
        mock_store = AsyncMock()
        with patch("services.memory.store_health_episode", mock_store):
            await _store_wearable_episodes("user-1", events)

        assert mock_store.call_count == 1  # one episode for the entire day

    async def test_average_value_stored(self):
        from routers.wearables import _store_wearable_episodes
        events = [
            {"user_id": "u", "biomarker_code": "8867-4", "occurred_at": "2024-06-15T09:00:00+00:00",
             "value_numeric": 60.0, "event_type": "heart_rate", "source": "fitbit"},
            {"user_id": "u", "biomarker_code": "8867-4", "occurred_at": "2024-06-15T12:00:00+00:00",
             "value_numeric": 80.0, "event_type": "heart_rate", "source": "fitbit"},
        ]
        mock_store = AsyncMock()
        with patch("services.memory.store_health_episode", mock_store):
            await _store_wearable_episodes("user-1", events)

        stored_event = mock_store.call_args[0][1]
        assert stored_event["value_numeric"] == 70.0

    async def test_separate_episode_per_biomarker(self):
        from routers.wearables import _store_wearable_episodes
        events = [
            {"user_id": "u", "biomarker_code": "8867-4", "occurred_at": "2024-06-15T09:00:00+00:00",
             "value_numeric": 72.0, "event_type": "heart_rate", "source": "fitbit"},
            {"user_id": "u", "biomarker_code": "55423-8", "occurred_at": "2024-06-15T18:00:00+00:00",
             "value_numeric": 8432.0, "event_type": "activity", "source": "fitbit"},
        ]
        mock_store = AsyncMock()
        with patch("services.memory.store_health_episode", mock_store):
            await _store_wearable_episodes("user-1", events)

        assert mock_store.call_count == 2

    async def test_cap_at_200_episodes(self):
        from routers.wearables import _store_wearable_episodes
        # Generate events across 250 distinct (date, biomarker) pairs
        events = [
            {
                "user_id": "u",
                "biomarker_code": f"code-{i % 25}",
                "occurred_at": f"2024-{(i // 25) + 1:02d}-01T00:00:00+00:00",
                "value_numeric": float(i),
                "event_type": "activity",
                "source": "fitbit",
            }
            for i in range(250)
        ]
        mock_store = AsyncMock()
        with patch("services.memory.store_health_episode", mock_store):
            await _store_wearable_episodes("user-1", events)

        assert mock_store.call_count <= 200

    async def test_skips_events_with_no_numeric_value(self):
        from routers.wearables import _store_wearable_episodes
        events = [
            {"user_id": "u", "biomarker_code": "8867-4", "occurred_at": "2024-06-15T09:00:00+00:00",
             "value_numeric": None, "event_type": "heart_rate", "source": "fitbit"},
        ]
        mock_store = AsyncMock()
        with patch("services.memory.store_health_episode", mock_store):
            await _store_wearable_episodes("user-1", events)

        mock_store.assert_not_called()

    async def test_episode_occurred_at_is_date_midnight(self):
        from routers.wearables import _store_wearable_episodes
        events = [
            {"user_id": "u", "biomarker_code": "8867-4", "occurred_at": "2024-06-15T09:23:45+00:00",
             "value_numeric": 72.0, "event_type": "heart_rate", "source": "fitbit"},
        ]
        mock_store = AsyncMock()
        with patch("services.memory.store_health_episode", mock_store):
            await _store_wearable_episodes("user-1", events)

        stored_event = mock_store.call_args[0][1]
        assert stored_event["occurred_at"] == "2024-06-15T00:00:00+00:00"

    async def test_error_per_episode_does_not_abort(self):
        from routers.wearables import _store_wearable_episodes
        events = [
            {"user_id": "u", "biomarker_code": "8867-4", "occurred_at": "2024-06-15T09:00:00+00:00",
             "value_numeric": 72.0, "event_type": "heart_rate", "source": "fitbit"},
            {"user_id": "u", "biomarker_code": "55423-8", "occurred_at": "2024-06-15T18:00:00+00:00",
             "value_numeric": 8000.0, "event_type": "activity", "source": "fitbit"},
        ]
        mock_store = AsyncMock(side_effect=[Exception("timeout"), None])
        with patch("services.memory.store_health_episode", mock_store):
            await _store_wearable_episodes("user-1", events)

        assert mock_store.call_count == 2


# ══════════════════════════════════════════════════════════════════════
# 7. _format_event_as_episode (episode body quality)
# ══════════════════════════════════════════════════════════════════════

class TestFormatEventAsEpisode:
    def test_includes_biomarker_name_value_unit_status(self):
        from services.memory import _format_event_as_episode
        event = {
            "event_type": "lab_result",
            "occurred_at": "2024-06-15T00:00:00+00:00",
            "biomarker_name": "HbA1c",
            "biomarker_code": "4548-4",
            "value_numeric": 7.2,
            "unit": "%",
            "status": "high",
            "source": "lab_report",
        }
        body = _format_event_as_episode(event)
        assert "HbA1c" in body
        assert "7.2" in body
        assert "%" in body
        assert "high" in body

    def test_handles_missing_biomarker(self):
        from services.memory import _format_event_as_episode
        event = {
            "event_type": "activity",
            "occurred_at": "2024-06-15T00:00:00+00:00",
            "source": "fitbit",
        }
        body = _format_event_as_episode(event)
        assert "activity" in body

    def test_includes_value_text_when_no_numeric(self):
        from services.memory import _format_event_as_episode
        event = {
            "event_type": "observation",
            "occurred_at": "2024-06-15T00:00:00+00:00",
            "value_text": "Mild fatigue noted",
            "source": "manual",
        }
        body = _format_event_as_episode(event)
        assert "Mild fatigue" in body
