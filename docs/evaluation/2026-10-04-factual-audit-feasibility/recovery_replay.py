"""Read-only replay of the exact stored native review; no MCP mutation or inference."""
from pathlib import Path
import hashlib
import json
import sqlite3
from rob2_kit.interfaces.mcp.server import (
    _review_target, _review_view_digest, _review_fragment_response,
)
R=Path(__file__).resolve().parent
ROOT=R.parents[2]
CASE=ROOT/'docs/evaluation/2026-10-04-gupta-fork-continuation'
M=json.loads((CASE/'run-manifest.json').read_text())
workspace=Path(M['staging'])/'workspace'
prefix=json.loads((ROOT/'docs/evaluation/2026-10-04-source-audit-design/native-measurement-review.json').read_text())
page=prefix['data']['review_page']
view_id=page['next_cursor'].split('.')[1]
database=workspace/'.rob2-kit/derivative.sqlite3'
before=hashlib.sha256(database.read_bytes()).hexdigest()
with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as con:
 row=con.execute('SELECT digest,selection,snapshot FROM review_views WHERE view_id=?',(view_id,)).fetchone()
assert row is not None
digest,selection,snapshot=row[0],json.loads(row[1]),json.loads(row[2])
assert _review_view_digest(snapshot,selection)==digest
kind,target=_review_target(snapshot,selection)
text=json.dumps(target,ensure_ascii=False,sort_keys=True,separators=(',',':'))
assert len(text)==page['total'] and text.startswith(page['fragment'])
position=text.index('13/86')
parts=[page['fragment']];offset=len(parts[0]);lengths=[offset]
while offset<len(text):
 recovered=_review_fragment_response(snapshot,snapshot,selection,digest,view_id,offset)
 detail=recovered['data']['review_page'];chunk=detail['fragment']
 assert detail['offset']==offset and chunk==text[offset:offset+len(chunk)]
 parts.append(chunk);lengths.append(len(chunk));offset+=len(chunk)
assert ''.join(parts)==text
assert json.loads(''.join(parts))==target
assert hashlib.sha256(database.read_bytes()).hexdigest()==before
question_sizes={}
for answer in target['answers']:
 selector={'domain_id':'domain:measurement','question_id':answer['question_id']}
 _,one=_review_target(snapshot,selector)
 encoded=json.dumps(one,ensure_ascii=False,sort_keys=True,separators=(',',':'))
 question_sizes[answer['question_id']]={'characters':len(encoded),'utf8_bytes':len(encoded.encode()),'contains_count_clause':'13/86' in encoded}
result={'answer_selector_target_sizes':question_sizes,'read_only_sqlite':True,'view_digest_verified':True,'native_prefix_characters':len(parts[0]),'full_projection_characters':len(text),'count_clause_position':position,'differential_question_position':text.index('sq:measurement:differential'),'missing_from_first_prefix':position>=len(parts[0]),'fragment_lengths':lengths,'additional_fragments_to_complete':len(parts)-1,'pure_recovery_reconstructs_exact_target':True,'derivative_database_unchanged':True,'instructions_already_explicit':'SKILL.md step7 says follow next_cursor and parse once complete; review_trial description supplies cursor and question selectors.','distinction':'Observable presentation burden: serialized cited facts precede relevant warrant and require additional retrieval. Observable follow-through failure: native model did not request the exposed cursor. No evidence of inaccessible evidence, broken recovery, or anchoring. No runtime change.'}
(R/'recovery-replay.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
