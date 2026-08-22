import pytest

from rob2_kit.evaluation.privacy import RetainedEvidenceManifest


def test_privacy_manifest_rejects_sources_text_and_paths():
    with pytest.raises(ValueError, match="forbidden"):
        RetainedEvidenceManifest.from_dict({"sources": ["private.pdf"]})
    with pytest.raises(ValueError, match="path-like"):
        RetainedEvidenceManifest.from_dict(
            {
                "schema_version": "v1",
                "run_id": "run-1",
                "identities": {},
                "timings": {},
                "counts": {},
                "hashes": {},
                "review_references": (),
                "final_references": (),
                "verifier_output": {"detail": "C:/private/run"},
                "config_before_hash": "sha256:a",
                "config_after_hash": "sha256:b",
            }
        )
