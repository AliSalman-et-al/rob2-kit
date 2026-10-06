from pathlib import Path
import runpy,sys,rob2_kit
r=Path(__file__).resolve().parent;repo=r.parent.parent
assert str(Path(rob2_kit.__file__).resolve()).startswith(str(r/'venv'))
sys.path.insert(0,str(repo/'tests'))
t=runpy.run_path(str(repo/'tests/test_official_question_qualifications.py'))
t['test_complete_elaborations_match_independently_captured_official_blocks']()
t['test_question_options_dependencies_and_wording_are_unchanged']()
t['test_native_context_preserves_both_sides_of_official_qualifications'](r/'synthetic-installed-qualification')
print('Existing three qualification checks pass against installed wheel; native D1/D3/D4 context preserves both sides of complete official qualifications.')
