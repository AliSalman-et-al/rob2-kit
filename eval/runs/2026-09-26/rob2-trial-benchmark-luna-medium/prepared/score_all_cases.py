from __future__ import annotations

import csv
import hashlib
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

campaign = Path(__file__).resolve().parents[1]
repo = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(repo / "src"))
sys.path.insert(0, str(repo / "scripts"))
from benchmark_contract import artifact_manifest_identity
from score_trial_benchmark import DOMAIN_KEYS, _load_reference, _norm_identity
from verify_bundle import verify

manifest_path = campaign / "prepared" / "trial-benchmark-manifest.v3.json"
reference = repo / "eval" / "reference"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
labels = _load_reference(reference)
rows: list[dict[str, Any]] = []
failures: list[dict[str, str]] = []

for item in manifest["rows"]:
    run_dir = Path(item["run_dir"]).resolve(strict=True)
    execution = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
    if execution.get("state") != "succeeded":
        failures.append({"outcome": item["outcome"], "trial": item["trial"], "reason": f"execution state={execution.get('state')}"})
        continue
    bundles = sorted(run_dir.rglob("*.rob2.zip"))
    if len(bundles) != 1:
        failures.append({"outcome": item["outcome"], "trial": item["trial"], "reason": f"expected one bundle, found {len(bundles)}"})
        continue
    bundle = bundles[0]
    artifact = execution.get("artifact") or {}
    recorded_path = (run_dir / str(artifact.get("path", ""))).resolve()
    if not artifact.get("verified") or recorded_path != bundle.resolve():
        failures.append({"outcome": item["outcome"], "trial": item["trial"], "reason": "execution artifact path or verification flag mismatch"})
        continue
    if hashlib.sha256(bundle.read_bytes()).hexdigest() != artifact.get("sha256"):
        failures.append({"outcome": item["outcome"], "trial": item["trial"], "reason": "execution artifact hash mismatch"})
        continue
    try:
        identity = artifact_manifest_identity(bundle)
    except Exception as exc:
        failures.append({"outcome": item["outcome"], "trial": item["trial"], "reason": f"artifact identity check failed: {exc}"})
        continue
    if identity != artifact.get("identity"):
        failures.append({"outcome": item["outcome"], "trial": item["trial"], "reason": "artifact identity mismatch"})
        continue
    ok, reason = verify(bundle)
    if not ok:
        failures.append({"outcome": item["outcome"], "trial": item["trial"], "reason": reason})
        continue
    with zipfile.ZipFile(bundle) as archive:
        canonical = json.loads(archive.read("canonical.json"))
    snapshots = canonical.get("snapshots")
    if not isinstance(snapshots, dict) or len(snapshots) != 1:
        failures.append({"outcome": item["outcome"], "trial": item["trial"], "reason": "canonical snapshot is missing or non-singular"})
        continue
    snapshot = next(iter(snapshots.values()))
    judgment = snapshot.get("domain_judgments") or {}
    observed = {d: judgment.get(DOMAIN_KEYS[d]) for d in DOMAIN_KEYS}
    observed["overall"] = snapshot.get("overall")
    if any(value not in {"low", "some_concerns", "high"} for value in observed.values()):
        failures.append({"outcome": item["outcome"], "trial": item["trial"], "reason": "canonical judgment label missing or invalid"})
        continue
    expected = labels.get((item["outcome"], item["trial"]))
    if expected is None:
        key = next((key for key in labels if key[0] == item["outcome"] and _norm_identity(key[1]) == _norm_identity(item["trial"])), None)
        expected = labels.get(key) if key else None
    if expected is None:
        failures.append({"outcome": item["outcome"], "trial": item["trial"], "reason": "catalog label missing"})
        continue
    rows.append({**item, "expected": expected, "observed": observed, "bundle": str(bundle), "bundle_sha256": artifact["sha256"], "bundle_identity": identity, "bundle_verified": True})


def rate(correct: int, total: int) -> dict[str, Any]:
    return {"correct": correct, "total": total, "rate": correct / total if total else None}


def metrics(group: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {"case_count": len(group), "overall": {}, "domains": {}, "pooled_domains": {}}
    for key in ("overall", *DOMAIN_KEYS):
        output["overall" if key == "overall" else "domains"][key if key != "overall" else "exact"] = None
    output["overall"] = {
        "exact": rate(sum(r["expected"]["overall"] == r["observed"]["overall"] for r in group), len(group)),
        "low_vs_non_low": rate(sum((r["expected"]["overall"] == "low") == (r["observed"]["overall"] == "low") for r in group), len(group)),
    }
    output["domains"] = {
        d: {
            "exact": rate(sum(r["expected"][d] == r["observed"][d] for r in group), len(group)),
            "low_vs_non_low": rate(sum((r["expected"][d] == "low") == (r["observed"][d] == "low") for r in group), len(group)),
        }
        for d in DOMAIN_KEYS
    }
    denominator = len(group) * len(DOMAIN_KEYS)
    output["pooled_domains"] = {
        "exact": rate(sum(r["expected"][d] == r["observed"][d] for r in group for d in DOMAIN_KEYS), denominator),
        "low_vs_non_low": rate(sum((r["expected"][d] == "low") == (r["observed"][d] == "low") for r in group for d in DOMAIN_KEYS), denominator),
    }
    output["domain_cells"] = denominator
    return output

by_outcome = {name: metrics([r for r in rows if r["outcome"] == name]) for name in sorted({r["outcome"] for r in rows})}
by_status = {name: metrics([r for r in rows if r["primary_status"] == name]) for name in ("primary", "secondary")}
by_outcome_status = {
    f"{outcome} / {status}": metrics([r for r in rows if r["outcome"] == outcome and r["primary_status"] == status])
    for outcome in sorted({r["outcome"] for r in rows})
    for status in ("primary", "secondary")
}
by_domain = {
    d: {
        "exact": rate(sum(r["expected"][d] == r["observed"][d] for r in rows), len(rows)),
        "low_vs_non_low": rate(sum((r["expected"][d] == "low") == (r["observed"][d] == "low") for r in rows), len(rows)),
    }
    for d in DOMAIN_KEYS
}
result = {
    "schema": "rob2-kit.user-requested-all-case-accuracy.v1",
    "manifest": str(manifest_path),
    "model": manifest["model"],
    "reasoning_effort": manifest["reasoning_effort"],
    "scope_policy": manifest["score_policy"],
    "cohort": {"manifest_cases": len(manifest["rows"]), "verified_scored_cases": len(rows), "excluded_or_invalid": len(failures), "outcome_cases": {k: sum(r["outcome"] == k for r in rows) for k in sorted({r["outcome"] for r in rows})}, "primary_cases": sum(r["primary_status"] == "primary" for r in rows), "secondary_cases": sum(r["primary_status"] == "secondary" for r in rows)},
    "accuracy": {"pooled": metrics(rows), "by_outcome": by_outcome, "by_domain": by_domain, "by_primary_status": by_status, "by_outcome_and_primary_status": by_outcome_status},
    "catalog_high_reference_count": sum(1 for r in rows for k,v in r["expected"].items() if v == "high"),
    "failures": failures,
    "cases": [{k:r[k] for k in ("outcome","trial","primary_status","role","definition","effect_size","source_locator","expected","observed","bundle","bundle_sha256","bundle_identity","scope_note")} for r in rows],
}
out_json = campaign / "all-case-accuracy.json"
out_json.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
out_tsv = campaign / "case-scores.tsv"
with out_tsv.open("w", encoding="utf-8", newline="") as stream:
    fields = ["outcome","trial","primary_status","role","definition","effect_size","source_locator","expected_D1","observed_D1","expected_D2","observed_D2","expected_D3","observed_D3","expected_D4","observed_D4","expected_D5","observed_D5","expected_overall","observed_overall","exact_domain_count","binary_domain_count","bundle_sha256","bundle_identity","scope_note"]
    writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    for r in rows:
        record={k:r.get(k,"") for k in fields}
        for d in DOMAIN_KEYS:
            record[f"expected_{d}"]=r["expected"][d]
            record[f"observed_{d}"]=r["observed"][d]
        record["expected_overall"]=r["expected"]["overall"]
        record["observed_overall"]=r["observed"]["overall"]
        record["exact_domain_count"]=sum(r["expected"][d]==r["observed"][d] for d in DOMAIN_KEYS)
        record["binary_domain_count"]=sum((r["expected"][d]=="low")== (r["observed"][d]=="low") for d in DOMAIN_KEYS)
        writer.writerow(record)
print(json.dumps({"scored_cases":len(rows),"failures":failures,"accuracy":result["accuracy"]["pooled"],"json":str(out_json),"tsv":str(out_tsv)},ensure_ascii=False))
if failures or len(rows) != len(manifest["rows"]):
    raise SystemExit(2)
