"""Exploratory generous component comparison; never used by product."""
from __future__ import annotations
import hashlib,json,re
from decimal import Decimal
from pathlib import Path
from rob2_kit.application.evidence import _NUMERIC_ATOM_PATTERN,_normalized_with_spans
R=Path(__file__).resolve().parent
ATOM=re.compile(rf'(?<![\w.]){_NUMERIC_ATOM_PATTERN}(?!\w)')
def values(text:str)->dict[Decimal,list[str]]:
 normalized,_=_normalized_with_spans(text)
 normalized=re.sub(r'(?<=\d)·(?=\d)', '.',normalized)
 result:dict[Decimal,list[str]]={}
 for m in ATOM.finditer(normalized):
  spelling=m.group();value=Decimal(spelling.replace(',',''));result.setdefault(value,[]).append(spelling)
 return result

def main()->None:
 assert not (R/'sensitivity-results.json').exists(),'Preserve first sensitivity result'
 p=R/'sensitivity-protocol.json';script=Path(__file__).resolve()
 freeze={'protocol_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'script_sha256':hashlib.sha256(script.read_bytes()).hexdigest(),'sample_sha256':hashlib.sha256((R/'sample.json').read_bytes()).hexdigest(),'after_primary_results':True}
 (R/'sensitivity-freeze.json').write_text(json.dumps(freeze,indent=2)+'\n',encoding='utf-8')
 rows=json.loads((R/'sample.json').read_text(encoding='utf-8'));out=[]
 for r in rows:
  material={s['evidence']['identity']:values(s['evidence'].get('quote',s['evidence'].get('transcription',''))) for s in r['selected']}
  checks=[{'value':str(v),'claim_spellings':spellings,'matching_evidence':[k for k,d in material.items() if v in d]} for v,spellings in values(r['answer']['justification']).items()]
  out.append({'case':r['case'],'question':r['answer']['question_id'],'sample_role':r['sample_role'],'numeric_values':checks,'absent_values':[c['value'] for c in checks if not c['matching_evidence']]})
 controls=[r for r in out if r['sample_role']=='control'];summary={'controls':len(controls),'flagged_controls':sum(bool(r['absent_values']) for r in controls),'absent_control_values':sum(len(r['absent_values']) for r in controls),'known_gap':[r['absent_values'] for r in out if r['sample_role']=='known_gap'],'model_calls':0,'runtime_changes':0}
 (R/'sensitivity-results.json').write_text(json.dumps({'summary':summary,'results':out},indent=2)+'\n',encoding='utf-8')
 print(json.dumps(summary));print('\n'.join(r['case']+' '+r['question']+': '+str(r['absent_values']) for r in out))
if __name__=='__main__':main()
