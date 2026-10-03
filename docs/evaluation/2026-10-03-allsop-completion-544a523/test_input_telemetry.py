"""Offline guard controls; this file never launches a model."""
import importlib.util
from pathlib import Path
from domain_probe_controls_telemetry import guard_stop

root = Path(__file__).parent
spec = importlib.util.spec_from_file_location("launcher", root / "run_full_case_544a523.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
_, limits, _ = launcher.load_controls(root)
assert limits.input_tokens is None and limits.uncached_input_tokens is None
usage = {"input_tokens": 10**15, "cached_input_tokens": 10**14, "output_tokens": 1}
state = dict(tools=1, saves=0, identical_rejections=0, wall_seconds=1, idle_seconds=1)
assert guard_stop(limits, usage, **state) is None
assert guard_stop(limits, {**usage, "output_tokens": 15000}, **state) == "output threshold"
for key, value, reason in [
    ("tools", 60, "tool limit"),
    ("saves", 4, "save attempt limit"),
    ("identical_rejections", 2, "repeated identical rejection"),
    ("wall_seconds", 1200, "wall threshold"),
    ("idle_seconds", 180, "idle threshold"),
]:
    assert guard_stop(limits, usage, **{**state, key: value}) == reason
print("telemetry-only input and six retained guard controls passed")
