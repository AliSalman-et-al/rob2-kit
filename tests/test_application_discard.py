from __future__ import annotations

from types import SimpleNamespace

from rob2_kit.interfaces.cli import app


def test_discard_is_cli_only_and_requires_fresh_exact_confirmation(monkeypatch, tmp_path) -> None:
    identity = "sha256:" + "a" * 64
    captured = {}
    monkeypatch.setattr(
        app,
        "current_batch_projection",
        lambda workspace: SimpleNamespace(approved_batch_ref=SimpleNamespace(identity=identity)),
    )

    def fake_discard(workspace, request):
        captured["request"] = request
        return SimpleNamespace(status="discarded", model_dump_json=lambda: '{"status":"discarded"}')

    monkeypatch.setattr(app, "discard_active_batch", fake_discard)
    answers = iter(["I_UNDERSTAND_THIS_DISCARDS_THE_ACTIVE_BATCH", "researcher requested cleanup"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    assert app.main(["discard", "--workspace", str(tmp_path)]) == 0
    assert captured["request"].confirmation == "I_UNDERSTAND_THIS_DISCARDS_THE_ACTIVE_BATCH"
    assert captured["request"].actor.startswith("cli:")
