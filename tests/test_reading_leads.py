from pathlib import Path

from rob2_kit.application._state import _state
from rob2_kit.application.domains import _reading_leads
from rob2_kit.application.intake import prepare_batch_for_outcome
from rob2_kit.application.source_handles import source_handle


def test_concealment_lead_points_to_the_protocol_page_that_describes_it(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "main.txt").write_text(
        "Patients were randomized and followed for twelve months.", encoding="utf-8"
    )
    (trial / "protocol.txt").write_text(
        "Allocation was concealed: a central web-based interactive response system "
        "assigned sequentially numbered, identical drug containers after enrolment.",
        encoding="utf-8",
    )
    (trial / "sources.toml").write_text(
        '[roles]\n"main.txt" = "main_article"\n"protocol.txt" = "protocol"\n', encoding="utf-8"
    )
    prepare_batch_for_outcome(tmp_path, "death", 0)
    sources = _state(tmp_path)["batch"]["trials"][0]["sources"]
    protocol = next(source for source in sources if source["label"] == "protocol.txt")

    leads = {
        lead["question_id"]: lead["pages"]
        for lead in _reading_leads(tmp_path, "trial", "domain:randomization", sources)
    }

    top = leads["sq:randomization:concealment"][0]
    assert top["source_id"] == source_handle(protocol["id"])
    assert top["read"]["windows"][0]["page"] == 1
