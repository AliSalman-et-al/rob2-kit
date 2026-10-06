"""Freeze preserved source access and an offline availability packet, without inference."""

import hashlib
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

from diagnostic_evidence_preflight import check_manifest

from rob2_kit.application._state import _projection_hash

root = Path(sys.argv[1])
public = Path(__file__).parent
repo = public.parents[2]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


bundle = root / "model-source-bundle"
files = sorted(p.name for p in bundle.iterdir() if p.is_file())
assert files == [
    "2159.pdf",
    "NCT01064687.original-projection.txt",
    "dc132760supplementarydata.pdf",
    "sources.toml",
]
expected = {
    "2159.pdf": "63cd5a3ff8875b21943f71cba0ec58fef741549f962132786cc1bf4a3b77270f",
    "dc132760supplementarydata.pdf": (
        "da0de5a1322d6eecaacc7413b471916a87d231a107ab3b6221b3b15d7d9b2886"
    ),
    "NCT01064687.original-projection.txt": (
        "9680cc92144bf1e3888e0826fbbe25931c25c2b938897ba04959ec714b62db8f"
    ),
}
for name, digest in expected.items():
    assert sha((bundle / name).read_bytes()) == digest
registry = (bundle / "NCT01064687.original-projection.txt").read_text()
assert (
    _projection_hash(
        "sha256:35aba4f0e44689a81610e95b405de5795e7b673f994d6d303f70e12706123bb1",
        "application/json",
        (registry,),
    )
    == "sha256:41d5c767dceed28cf46a137377106a310aac69246837768dc20b375121d28cd8"
)
prompt = (
    "Assess domain:missing for the approved AWARD-1 Result using "
    "the available Sources and full official D3 context. Use the "
    "normal native tools to inspect sources and save a supported "
    "complete active-path judgment with explicit unknowns and cou"
    "nterevidence. Stop after the accepted D3 checkpoint.\n"
)
(public / "model-task.txt").write_text(prompt)
packet = bytearray(prompt.encode())
required = []
supplied = []
for name, identity in [
    ("2159.pdf", "source_9c930b3bf92f1574811a437f9f437b764e5e20c57ff42b278479199ead8c5ab8"),
    (
        "dc132760supplementarydata.pdf",
        "source_af5af683eff6bed3bd60bb4948e6f0ecd0b94046f164c4f738e09b22c23371ff",
    ),
    (
        "NCT01064687.original-projection.txt",
        "source_9062b2816dbd4d98622ac8bedb67562f92878839d52af46f83c04ad122943cfb",
    ),
]:
    pages = (
        [registry]
        if name.endswith(".txt")
        else json.loads((root / f"{name}.pages.json").read_text())
    )
    for page, text in enumerate(pages, 1):
        packet.extend(f"\nSOURCE {name} PAGE {page}\n".encode())
        data = text.encode()
        start = len(packet)
        packet.extend(data)
        window = {
            "source_identity": identity,
            "page": page,
            "start_line": 1,
            "end_line": len(text.splitlines()),
        }
        required.append(window)
        supplied.append(
            {
                **window,
                "input_start_byte": start,
                "input_end_byte": len(packet),
                "text_sha256": sha(data),
            }
        )
images = []
supplied_images = []
for page in [3, 5]:
    data = (root / f"main-page{page}.png").read_bytes()
    width, height = struct.unpack(">II", data[16:24])
    packet.extend(f"\nSOURCE 2159.pdf PAGE {page} FULL PNG\n".encode())
    start = len(packet)
    packet.extend(data)
    frame = {
        "source_identity": (
            "source_9c930b3bf92f1574811a437f9f437b764e5e20c57ff42b278479199ead8c5ab8"
        ),
        "page": page,
        "png_sha256": sha(data),
        "width": width,
        "height": height,
    }
    images.append(frame)
    supplied_images.append({**frame, "input_start_byte": start, "input_end_byte": len(packet)})
packet_path = root / "source-availability-packet.bin"
packet_path.write_bytes(packet)
availability = {
    "research_question": (
        "Does the existing lean evidence path retain full source/inte"
        "rpretation provenance and permit source-faithful D3 warrants"
        " on this disclosed development case?"
    ),
    "input_sha256": sha(packet),
    "required_windows": required,
    "supplied_windows": supplied,
    "required_images": images,
    "supplied_images": supplied_images,
}
(root / "availability-manifest.json").write_text(json.dumps(availability, indent=2) + "\n")
checked = check_manifest(root / "availability-manifest.json", packet_path)
(root / "availability-preflight.json").write_text(json.dumps(checked, indent=2) + "\n")
baseline = "247db8c805c34923e2cd086124b084d040121834"
lean = "55ccc7a3cdd8352c025aa15b9fc039dac6f9f58d"
current = "e6b13031ddfa72437f3e1f2f9ca3b38ea58a064c"
code = {}
for name in [
    "src/rob2_kit/packs/d3_authoritative.py",
    "src/rob2_kit/packs/scientific.py",
    "src/rob2_kit/logic/evaluator.py",
    "uv.lock",
]:
    code[name] = {
        head: sha(subprocess.check_output(["git", "show", f"{head}:{name}"], cwd=repo))
        for head in [baseline, lean, current]
    }
    assert len(set(code[name].values())) == 1
manifest = {
    "case": "award-1-2014",
    "status": "preparation_only_parent_review_and_separate_inference_authorization_pending",
    "exposure": "Paid development run and source-informed D3.4 tuning; not held out",
    "baseline_sha": baseline,
    "lean_checkpoint_sha": lean,
    "current_production_sha": current,
    "sources": [
        {
            "path": str(bundle / name),
            "sha256": sha((bundle / name).read_bytes()),
            "kind": "preserved_registry_projection_not_raw_JSON"
            if name.endswith(".txt")
            else "original_Code_PDF"
            if name.endswith(".pdf")
            else "roles_only_no_network_lookup",
        }
        for name in files
    ],
    "original_raw_registry_sha256_unrecovered": (
        "35aba4f0e44689a81610e95b405de5795e7b673f994d6d303f70e12706123bb1"
    ),
    "separate_new_registry_capture_excluded": True,
    "result_file": str(root / "approved-offline-result.json"),
    "result_sha256": sha((root / "approved-offline-result.json").read_bytes()),
    "model_task_sha256": sha(prompt.encode()),
    "full_source_access": True,
    "excluded_from_model_input": [
        "review-dossier.md",
        "offline fixture answers/label",
        "prior assessments/gold",
        "cross-case premise inventory",
        "private test criteria",
        "new registry capture",
    ],
    "availability_check": checked,
    "availability_is_not_actual_model_delivery_or_scientific_sufficiency": True,
    "identical_scientific_and_environment_file_hashes": code,
    "settings": {
        "model": "gpt-6-luna",
        "reasoning_effort": "medium",
        "launcher": (
            "codex exec --strict-config --ignore-rules --skip-git-repo-ch"
            "eck -s read-only -m gpt-6-luna"
        ),
        "mcp": "mcp-codex direct namespace mcp__rob2",
        "guidance_profile": "official_d3_prototype",
        "shell_web_apps_delegation": "disabled",
        "python": "/home/ali/Documents/Codex/2026-10-02/task/rob2-kit/.venv/bin/python",
        "guards": {
            "tool_count_stop": False,
            "input_token_stop": False,
            "output_review_threshold": 6000,
            "wall_review_seconds": 480,
            "idle_review_seconds": 90,
            "identical_rejected_submissions_stop": 3,
            "supervised": True,
        },
        "invocations_authorized_now": 0,
        "continuations_or_retries": 0,
    },
    "next_launch_requirement": (
        "Separate source review and explicit call count authorization"
        ", then launch_checked with exact staged input/manifest hashe"
        "s; no launch in this preparation."
    ),
}
(public / "frozen-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
for name in [
    "offline-validation.json",
    "availability-preflight.json",
    "availability-manifest.json",
]:
    shutil.copyfile(root / name, public / name)
print(json.dumps(checked, indent=2))
