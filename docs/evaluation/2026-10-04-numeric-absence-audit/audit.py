"""Frozen offline lexical hypothesis; produces no runtime review annotation."""
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
from typing import Any
from rob2_kit.application.evidence import (
    _NUMERIC_ATOM_PATTERN, _normalized_with_spans, _numeric_contains,
)
R=Path(__file__).resolve().parent
# Only presentation normalization and the existing numeric atom spelling.
EXPRESSIONS=re.compile(rf'(?<![\w.]){_NUMERIC_ATOM_PATTERN}(?:\s*/\s*{_NUMERIC_ATOM_PATTERN})?\s*%?(?!\w)')
def sha(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()
def inspect(row:dict[str,Any])->dict[str,Any]:
 text,_=_normalized_with_spans(row['answer']['justification']);expressions:dict[str,list[list[int]]]={}
 for match in EXPRESSIONS.finditer(text):
  literal=match.group().strip();expressions.setdefault(literal,[]).append([match.start(),match.end()])
 checks=[]
 for literal,positions in expressions.items():
  value=literal.removesuffix('%').strip()
  matches=[{'evidence':s['evidence']['identity'],'role':s['role']} for s in row['selected'] if _numeric_contains(s['evidence'].get('quote',s['evidence'].get('transcription','')),value,allow_percent_suffix=True)]
  checks.append({'expression':literal,'normalized_positions':positions,'selected_matches':matches,'literal_absent':not matches})
 typed=row['answer'].get('missing_data') or {};typed_rows=typed.get('rows',[])
 fields=('randomized','eligible','treated','observed','analyzed','imputed','excluded','event_count','missing')
 typed_checks=[]
 for index,t in enumerate(typed_rows):
  for field in fields:
   if t.get(field) is None:continue
   selected=[s for s in row['selected'] if s['evidence']['identity'] in t.get('basis',[])]
   matches=[s['evidence']['identity'] for s in selected if _numeric_contains(s['evidence'].get('quote',s['evidence'].get('transcription','')),str(t[field]),allow_percent_suffix=True)]
   typed_checks.append({'row':index,'field':field,'value':t[field],'selected_matches':matches,'literal_absent':not matches,'typed_scope':t['scope']})
 return {'case':row['case'],'question':row['answer']['question_id'],'sample_role':row['sample_role'],'expressions':checks,'absent':[c['expression'] for c in checks if c['literal_absent']],'flagged':any(c['literal_absent'] for c in checks),'typed_rows':len(typed_rows),'typed_quantity_checks':typed_checks,'basis_roles':[s['role'] for s in row['selected']],'existing_exact_recovery_actions':[s['recovery'] for s in row['selected']],'automatic_annotation_added':False}
def main()->None:
 f=json.loads((R/'freeze.json').read_text(encoding='utf-8'))
 for name,key in [('protocol.json','protocol_sha256'),('sample.json','sample_sha256'),('audit.py','algorithm_sha256')]:assert sha(R/name)==f[key]
 for p,h in f['bundles'].items():assert sha(Path(p))==h
 rows=json.loads((R/'sample.json').read_text(encoding='utf-8'));results=[inspect(r) for r in rows]
 controls=[r for r in results if r['sample_role']=='control'];positive=[r for r in results if r['sample_role']=='known_gap']
 summary={'controls':len(controls),'control_cases':len({r['case'] for r in controls}),'flagged_controls':sum(r['flagged'] for r in controls),'control_expressions':sum(len(r['expressions']) for r in controls),'absent_control_expressions':sum(len(r['absent']) for r in controls),'known_gap_flags':[{'case':r['case'],'absent':r['absent']} for r in positive],'model_calls':0,'mutations':0,'runtime_annotations':0,'control_absence_is_not_yet_semantic_adjudication':True}
 (R/'results.json').write_text(json.dumps({'summary':summary,'results':results},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 for p,h in f['bundles'].items():assert sha(Path(p))==h
 print(json.dumps(summary));print('\n'.join(r['case']+' '+r['question']+': '+str(r['absent']) for r in results))
if __name__=='__main__':main()
