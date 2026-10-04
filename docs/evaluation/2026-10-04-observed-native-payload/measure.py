"""Measure permitted existing rollout outputs; never read credentials or session metadata."""

import argparse
import collections
import hashlib
import json
from pathlib import Path


def size(value):
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rollout", type=Path)
    parser.add_argument("tools", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("instructions", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    counts = collections.Counter()
    sizes = collections.Counter()
    strings = collections.defaultdict(list)
    normative = collections.Counter()
    recovery = collections.Counter()
    source_bytes = 0
    raw_bytes = 0
    calls = []
    normative_keys = {
        "official_guidance",
        "guidance",
        "response_framework",
        "traps",
        "completion_rule",
        "answer_anchors",
        "decision_rule",
        "considerations",
        "invalid_shortcuts",
        "no_information_rule",
        "evidence_needed",
        "bias_construct",
        "propositions",
        "paired_examples",
    }
    recovery_keys = {
        "head",
        "context_page",
        "reading_recovery",
        "evidence_workspace",
        "investigation",
        "coverage",
        "remaining_windows",
        "page_remainder",
        "next_start_line",
        "next_start_char",
        "passage_ref",
    }

    def walk(value, path):
        nonlocal source_bytes
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"quote", "numbered_text"} and isinstance(item, str):
                    source_bytes += len(item.encode())
                if key in normative_keys:
                    normative[key] += size(item)
                if key in recovery_keys:
                    recovery[key] += size(item)
                walk(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
        elif isinstance(value, str) and len(value) > 100:
            strings[value].append(path)

    for line in args.rollout.open():
        record = json.loads(line)
        # Deliberately do not inspect session_meta, world_state, or encrypted reasoning.
        if record.get("type") != "response_item":
            continue
        payload = record["payload"]
        if payload.get("type") == "function_call":
            calls.append(payload["name"])
        if payload.get("type") != "function_call_output":
            continue
        name = calls[-1]
        raw = payload["output"]
        output = json.loads(raw.split("Output:\n", 1)[1])
        counts[name] += 1
        sizes[name] += size(output)
        raw_bytes += len(raw.encode())
        walk(output, f"{name}#{counts[name]}")

    tools = json.loads(args.tools.read_text())
    config = args.config.read_text()
    enabled = [tool for tool in tools if f'"{tool["name"]}"' in config]
    metrics = {
        "source": "Existing completed Bagg native D5; no new inference",
        "enabled_tools": [tool["name"] for tool in enabled],
        "exported_definition_reconstruction_bytes": {
            key: sum(size(tool[key]) for tool in enabled if key in tool)
            for key in ("input_schema", "output_schema", "description", "meta")
        },
        "provider_tool_serialization_retained": False,
        "instructions_bytes": args.instructions.stat().st_size,
        "recorded_function_calls": len(calls),
        "recorded_provider_visible_tool_outputs": sum(counts.values()),
        "final_save_output_absent_from_rollout": calls[-1] == "save_domain_judgment",
        "observed_tool_output_text_bytes": raw_bytes,
        "observed_compact_json_bytes": sum(sizes.values()),
        "by_tool": {
            name: {"outputs": counts[name], "compact_json_bytes": sizes[name]} for name in counts
        },
        "source_text_string_utf8_bytes": source_bytes,
        "normative_field_bytes": dict(normative),
        "recovery_field_bytes": dict(recovery),
        "exact_repeated_long_strings": [
            {
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
                "bytes_each": len(text.encode()),
                "paths": paths,
            }
            for text, paths in strings.items()
            if len(paths) > 1
        ],
        "limits": [
            "Nested category fields overlap; do not add category bytes.",
            "Exported definitions are reconstruction, not retained provider serialization.",
            "Byte counts are not token estimates; no quotes or account metadata exported.",
            "Final accepted save receipt had no following provider response.",
        ],
    }
    args.output.write_text(json.dumps(metrics, indent=2) + "\n")


if __name__ == "__main__":
    main()
