from __future__ import annotations

from workflow_code_skeleton.app.services.deepseek_agent import DeepSeekAgentClient


def test_complete_json_accepts_markdown_fence_without_retry(monkeypatch) -> None:
    client = DeepSeekAgentClient()
    calls = []

    def fake_complete(*_args, **_kwargs):
        calls.append(1)
        return {
            "message": {"content": "```json\n{\"ok\": true, \"value\": 3}\n```"},
            "usage": {},
            "model": "test",
            "request_id": "request",
        }

    monkeypatch.setattr(client, "complete", fake_complete)

    result = client.complete_json("return json")

    assert result["structured_output"] == {"ok": True, "value": 3}
    assert len(calls) == 1


def test_complete_json_extracts_object_from_short_explanation(monkeypatch) -> None:
    client = DeepSeekAgentClient()

    monkeypatch.setattr(
        client,
        "complete",
        lambda *_args, **_kwargs: {
            "message": {"content": "结果如下：\n{\"status\": \"ready\"}\n以上。"},
            "usage": {},
            "model": "test",
            "request_id": "request",
        },
    )

    assert client.complete_json("return json")["structured_output"]["status"] == "ready"
