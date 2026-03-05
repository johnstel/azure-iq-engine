"""
Tests for the quiz / learn endpoints:
  POST /api/quiz/generate
  POST /api/quiz/grade
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app, _quiz_sessions
from src.api.models import (
    QuizGenerateRequest,
    QuizGradeRequest,
    QuizAnswer,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

STUB_MC_QUESTION = json.dumps([
    {
        "id": "q1",
        "question": "Which layer of the Microsoft IQ stack focuses on knowledge work?",
        "type": "multiple_choice",
        "choices": [
            {"key": "A", "text": "Work IQ"},
            {"key": "B", "text": "Fabric IQ"},
            {"key": "C", "text": "Foundry IQ"},
            {"key": "D", "text": "Azure IQ"},
        ],
        "correct_answer": "A",
        "explanation": "Work IQ is the layer focused on knowledge work and Microsoft 365.",
        "difficulty": "beginner",
        "topic": "IQ Layers Overview",
        "iq_layer": "work-iq",
    }
])

STUB_FF_QUESTION = json.dumps([
    {
        "id": "q1",
        "question": "Describe the purpose of Fabric IQ in one sentence.",
        "type": "free_form",
        "choices": None,
        "correct_answer": "Fabric IQ unifies data analytics across the Microsoft platform.",
        "explanation": "Fabric IQ provides a unified analytics experience.",
        "difficulty": "intermediate",
        "topic": "Fabric IQ",
        "iq_layer": "fabric-iq",
    }
])


def _inject_session(correct_answer: str = "A", q_type: str = "multiple_choice") -> tuple[str, str]:
    """Inject a fake quiz session directly into the in-process store and return (session_id, q_id)."""
    session_id = str(uuid.uuid4())
    q_id = "q1"
    _quiz_sessions[session_id] = {
        q_id: {
            "correct_answer": correct_answer,
            "explanation": "Test explanation.",
            "type": q_type,
        }
    }
    return session_id, q_id


# ── Generate endpoint ─────────────────────────────────────────────────────────

class TestQuizGenerate:
    def test_generate_returns_session_and_questions(self, client: TestClient) -> None:
        """Generate should return a session_id and questions list (with mocked LLM/search)."""
        with (
            patch("src.api.main._search_index", new_callable=AsyncMock, return_value=[]),
            patch("src.api.main._call_openai", new_callable=AsyncMock, return_value=(STUB_MC_QUESTION, 100)),
        ):
            res = client.post("/api/quiz/generate", json={"count": 1, "difficulty": "beginner"})

        assert res.status_code == 200, res.text
        data = res.json()
        assert "session_id" in data
        assert isinstance(data["questions"], list)
        assert len(data["questions"]) >= 1
        assert data["difficulty"] == "beginner"

    def test_generate_question_has_no_correct_answer(self, client: TestClient) -> None:
        """Correct answers must not be exposed in the generate response."""
        with (
            patch("src.api.main._search_index", new_callable=AsyncMock, return_value=[]),
            patch("src.api.main._call_openai", new_callable=AsyncMock, return_value=(STUB_MC_QUESTION, 100)),
        ):
            res = client.post("/api/quiz/generate", json={"count": 1})

        assert res.status_code == 200
        for q in res.json()["questions"]:
            assert "correct_answer" not in q

    def test_generate_mc_question_has_choices(self, client: TestClient) -> None:
        """Multiple-choice questions must include choices."""
        with (
            patch("src.api.main._search_index", new_callable=AsyncMock, return_value=[]),
            patch("src.api.main._call_openai", new_callable=AsyncMock, return_value=(STUB_MC_QUESTION, 100)),
        ):
            res = client.post("/api/quiz/generate", json={"question_type": "multiple_choice", "count": 1})

        assert res.status_code == 200
        q = res.json()["questions"][0]
        assert q["type"] == "multiple_choice"
        assert isinstance(q["choices"], list)
        assert len(q["choices"]) == 4

    def test_generate_session_stored(self, client: TestClient) -> None:
        """After generate, session should be stored in the in-process store."""
        with (
            patch("src.api.main._search_index", new_callable=AsyncMock, return_value=[]),
            patch("src.api.main._call_openai", new_callable=AsyncMock, return_value=(STUB_MC_QUESTION, 100)),
        ):
            res = client.post("/api/quiz/generate", json={"count": 1})

        session_id = res.json()["session_id"]
        assert session_id in _quiz_sessions

    def test_generate_fallback_on_bad_llm_json(self, client: TestClient) -> None:
        """When LLM returns invalid JSON the endpoint should still return 200 with a fallback question."""
        with (
            patch("src.api.main._search_index", new_callable=AsyncMock, return_value=[]),
            patch("src.api.main._call_openai", new_callable=AsyncMock, return_value=("not valid json", 0)),
        ):
            res = client.post("/api/quiz/generate", json={"count": 1})

        assert res.status_code == 200
        data = res.json()
        assert len(data["questions"]) >= 1

    def test_generate_with_iq_layer_filter(self, client: TestClient) -> None:
        """IQ layer filter should be accepted without error."""
        with (
            patch("src.api.main._search_index", new_callable=AsyncMock, return_value=[]),
            patch("src.api.main._call_openai", new_callable=AsyncMock, return_value=(STUB_MC_QUESTION, 100)),
        ):
            res = client.post(
                "/api/quiz/generate",
                json={"iq_layer": "fabric-iq", "difficulty": "advanced", "count": 1},
            )

        assert res.status_code == 200

    def test_generate_with_domain_mapping(self, client: TestClient) -> None:
        """Certification domain mapping should be accepted and echoed back."""
        with (
            patch("src.api.main._search_index", new_callable=AsyncMock, return_value=[]),
            patch("src.api.main._call_openai", new_callable=AsyncMock, return_value=(STUB_MC_QUESTION, 100)),
        ):
            res = client.post(
                "/api/quiz/generate",
                json={"domain": "DP-600", "count": 1},
            )

        assert res.status_code == 200
        assert res.json()["domain"] == "DP-600"

    def test_generate_count_validation(self, client: TestClient) -> None:
        """count > 10 should return 422."""
        res = client.post("/api/quiz/generate", json={"count": 99})
        assert res.status_code == 422

    def test_generate_invalid_difficulty(self, client: TestClient) -> None:
        """Unknown difficulty should return 422."""
        res = client.post("/api/quiz/generate", json={"difficulty": "expert"})
        assert res.status_code == 422


# ── Grade endpoint ────────────────────────────────────────────────────────────

class TestQuizGrade:
    def test_grade_correct_mc(self, client: TestClient) -> None:
        """Correct multiple-choice answer should yield score=1.0, correct=True."""
        session_id, q_id = _inject_session(correct_answer="A", q_type="multiple_choice")

        res = client.post(
            "/api/quiz/grade",
            json={"session_id": session_id, "answers": [{"question_id": q_id, "answer": "A"}]},
        )

        assert res.status_code == 200, res.text
        data = res.json()
        assert data["correct_count"] == 1
        assert data["total_count"] == 1
        assert data["total_score"] == 1.0
        result = data["results"][0]
        assert result["correct"] is True
        assert result["score"] == 1.0
        assert result["correct_answer"] == "A"

    def test_grade_wrong_mc(self, client: TestClient) -> None:
        """Wrong multiple-choice answer should yield score=0.0, correct=False."""
        session_id, q_id = _inject_session(correct_answer="A", q_type="multiple_choice")

        res = client.post(
            "/api/quiz/grade",
            json={"session_id": session_id, "answers": [{"question_id": q_id, "answer": "B"}]},
        )

        assert res.status_code == 200
        data = res.json()
        assert data["correct_count"] == 0
        assert data["results"][0]["correct"] is False
        assert data["results"][0]["score"] == 0.0

    def test_grade_mc_case_insensitive(self, client: TestClient) -> None:
        """MC grading should be case-insensitive."""
        session_id, q_id = _inject_session(correct_answer="A", q_type="multiple_choice")

        res = client.post(
            "/api/quiz/grade",
            json={"session_id": session_id, "answers": [{"question_id": q_id, "answer": "a"}]},
        )

        assert res.status_code == 200
        assert res.json()["results"][0]["correct"] is True

    def test_grade_free_form_uses_llm(self, client: TestClient) -> None:
        """Free-form grading should call the LLM and use its score."""
        session_id, q_id = _inject_session(
            correct_answer="Fabric IQ unifies analytics.", q_type="free_form"
        )

        mock_llm_response = json.dumps({"score": 0.9, "feedback": "Great answer!"})
        with patch("src.api.main._call_openai", new_callable=AsyncMock, return_value=(mock_llm_response, 50)):
            res = client.post(
                "/api/quiz/grade",
                json={"session_id": session_id, "answers": [{"question_id": q_id, "answer": "Fabric IQ unifies all analytics."}]},
            )

        assert res.status_code == 200
        result = res.json()["results"][0]
        assert result["score"] == pytest.approx(0.9, abs=0.01)
        assert result["feedback"] == "Great answer!"
        assert result["correct"] is True  # >= 0.7 threshold

    def test_grade_unknown_session(self, client: TestClient) -> None:
        """Unknown session_id should return 404."""
        res = client.post(
            "/api/quiz/grade",
            json={"session_id": str(uuid.uuid4()), "answers": [{"question_id": "q1", "answer": "A"}]},
        )
        assert res.status_code == 404

    def test_grade_explanation_returned(self, client: TestClient) -> None:
        """Grade response must include the explanation text."""
        session_id, q_id = _inject_session(correct_answer="A", q_type="multiple_choice")

        res = client.post(
            "/api/quiz/grade",
            json={"session_id": session_id, "answers": [{"question_id": q_id, "answer": "A"}]},
        )

        result = res.json()["results"][0]
        assert "explanation" in result
        assert len(result["explanation"]) > 0

    def test_grade_missing_answers_field(self, client: TestClient) -> None:
        """Missing answers field should return 422."""
        res = client.post("/api/quiz/grade", json={"session_id": "abc"})
        assert res.status_code == 422

    def test_grade_roundtrip_generate_then_grade(self, client: TestClient) -> None:
        """Full round-trip: generate → grade."""
        with (
            patch("src.api.main._search_index", new_callable=AsyncMock, return_value=[]),
            patch("src.api.main._call_openai", new_callable=AsyncMock, return_value=(STUB_MC_QUESTION, 100)),
        ):
            gen_res = client.post("/api/quiz/generate", json={"count": 1})

        assert gen_res.status_code == 200
        gen_data = gen_res.json()
        session_id = gen_data["session_id"]
        q_id = gen_data["questions"][0]["id"]

        grade_res = client.post(
            "/api/quiz/grade",
            json={"session_id": session_id, "answers": [{"question_id": q_id, "answer": "A"}]},
        )
        assert grade_res.status_code == 200
        grade_data = grade_res.json()
        assert grade_data["total_count"] == 1
        assert "results" in grade_data


# ── Model validation ──────────────────────────────────────────────────────────

class TestQuizModels:
    def test_quiz_generate_request_defaults(self) -> None:
        req = QuizGenerateRequest()
        assert req.difficulty == "intermediate"
        assert req.question_type == "multiple_choice"
        assert req.count == 5

    def test_quiz_generate_request_count_bounds(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            QuizGenerateRequest(count=0)
        with pytest.raises(ValidationError):
            QuizGenerateRequest(count=11)

    def test_quiz_grade_request_requires_answers(self) -> None:
        from pydantic import ValidationError
        # Empty list should fail (min_length=1)
        with pytest.raises(ValidationError):
            QuizGradeRequest(session_id="abc", answers=[])
        # Omitting answers field entirely should also fail
        with pytest.raises(ValidationError):
            QuizGradeRequest(session_id="abc")
