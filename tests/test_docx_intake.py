from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

from rob2_kit.application.intake import prepare_batch
from rob2_kit.workflow_models import TrialDeclaration

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx_bytes(
    *,
    paragraph: str = "Paragraph",
    with_table: bool = True,
    with_footnotes: bool = True,
    with_reference: bool = True,
) -> bytes:
    table = (
        "<w:tbl>"
        "<w:tr><w:trPr><w:tblHeader/></w:trPr>"
        "<w:tc><w:p><w:r><w:t>Header A</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>Header B</w:t></w:r></w:p></w:tc></w:tr>"
        "<w:tr><w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>Cell B</w:t></w:r></w:p></w:tc></w:tr>"
        "</w:tbl>"
        if with_table
        else ""
    )
    reference = '<w:footnoteReference w:id="2"/>' if with_reference else ""
    document = (
        f'<w:document xmlns:w="{_W_NS}"><w:body>'
        f"<w:p><w:r><w:t>{paragraph}</w:t>{reference}</w:r></w:p>{table}"
        "<w:sectPr/></w:body></w:document>"
    )
    footnotes = (
        f'<w:footnotes xmlns:w="{_W_NS}">'
        '<w:footnote w:id="-1"><w:p/></w:footnote>'
        '<w:footnote w:id="2"><w:p><w:r><w:t>Footnote detail</w:t></w:r></w:p></w:footnote>'
        "</w:footnotes>"
        if with_footnotes
        else None
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", document)
        if footnotes is not None:
            archive.writestr("word/footnotes.xml", footnotes)
    return output.getvalue()


def _prepare(tmp_path: Path) -> dict[str, Any]:
    return prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="outcome")],
        expected_revision=0,
    )


def test_docx_roles_omissions_backups_and_missing_declarations_are_distinct(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "protocol.docx").write_bytes(_docx_bytes())
    (trial / "ignored.txt").write_text("intentionally ignored", encoding="utf-8")
    for suffix in (".2026-09-01", ".backup", ".orig", "~"):
        (trial / f"sources.toml{suffix}").write_text("not config", encoding="utf-8")
    (trial / "sources.toml").write_text(
        'sources = [{ path = "missing-list.docx", role = "protocol" }]\n'
        'omissions = ["ignored.txt"]\n'
        '[roles]\n"protocol.docx" = "protocol"\n"missing-role.docx" = "supplement"\n',
        encoding="utf-8",
    )

    prepared = _prepare(tmp_path)
    source = prepared["trials"][0]["sources"][0]
    assert source["logical_path"] == "protocol.docx"
    assert source["role"] == "protocol"
    conditions = [item for item in prepared["conditions"] if "path" in item]
    by_path = {item["path"]: item for item in conditions}
    assert by_path["missing-role.docx"]["code"] == "declared_source_missing"
    assert by_path["missing-list.docx"]["code"] == "declared_source_missing"
    assert "ignored.txt" not in by_path
    assert not any(path.startswith("sources.toml.") for path in by_path)
