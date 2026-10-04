"""Freeze full domain exports and exact supplied spans; no inference."""
from pathlib import Path
import hashlib
import json
import subprocess
import tomllib
from scripts.export_factual_audit import export_packet, INSTRUCTION
from scripts.diagnostic_evidence_preflight import check_manifest

R = Path(__file__).resolve().parent
ROOT = R.parents[2]
HOME = ROOT.parent / 'diagnostics/d3-guidance-pair-20261003/new/home'
WORK = HOME.parent

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def write(name, obj): (R / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')

assert not (R / 'manifest.json').exists(), 'No regeneration after freeze'
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip() == 'd6bdae597e72d4ff6221bc2dc65aa1e44fc4ea2f'
specs = [
 ('gupta-2024', 'domain:measurement', ROOT / 'docs/evaluation/2026-10-04-gupta-fork-continuation/caf5f259a9f5eef456a05a6543fac933aa9bcbc55a99ba4b03430da8b760ab2d.rob2.zip'),
 ('dapa-hf', 'domain:selection', ROOT.parent / 'diagnostics/cases/dapa-hf/.rob2-kit/finalized/00446bb5d9fd64b3ad27b1f1b804c94f26678c9149ce2244f7f3d2f2db9f1593.rob2.zip'),
]
input_text = INSTRUCTION + '\nAudit every claim in both Domains below. Answer in at most 2200 words. No tools or external research.\n\n'
windows=[];packets=[];claim_receipts=[];protected={}
for trial,domain,bundle in specs:
 packet=export_packet(bundle,trial,domain);packets.append(packet);protected[str(bundle)]=sha(bundle)
 write(trial+'-export.json',packet)
 # Preserve every claim and citation role; only full source text is relocated below.
 head={k:v for k,v in packet.items() if k not in ['instruction','cited_spans']}
 encoded=json.dumps(head,ensure_ascii=False,indent=2)
 input_text += encoded + '\n\nCited spans:\n'
 for claim in packet['claims']:
  claim_receipts.append({'trial_id':trial,'question_id':claim['question_id'],'claim_sha256':hashlib.sha256(json.dumps(claim,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),'citation_count':len(claim['citations'])})
 for span in packet['cited_spans']:
  meta={k:v for k,v in span.items() if k!='numbered_text'}
  input_text+=json.dumps(meta,ensure_ascii=False)+'\n'
  start=len(input_text.encode());input_text+=span['numbered_text'];end=len(input_text.encode());input_text+='\n\n'
  windows.append({'source_identity':span['source_identity'],'page':span['page'],'start_line':span['start_line'],'end_line':span['end_line'],'input_start_byte':start,'input_end_byte':end,'text_sha256':hashlib.sha256(span['numbered_text'].encode()).hexdigest()})
(R/'panel-input.txt').write_text(input_text)
write('panel-evidence-manifest.json',{'research_question':'Can one tool-free audit of all saved claims and existing cited spans identify unsupported attribution while preserving supported facts and qualified inference?','input_sha256':sha(R/'panel-input.txt'),'required_windows':[{k:w[k] for k in ['source_identity','page','start_line','end_line']} for w in windows],'supplied_windows':windows})
write('coverage-check.json',check_manifest(R/'panel-evidence-manifest.json',R/'panel-input.txt'))
# Freeze the scoring units before response: every saved warrant sentence and every limitation.
units=[]
for packet in packets:
 for claim in packet['claims']:
  sentences=claim['justification'].split('. ')
  for n,sentence in enumerate(sentences,1):
   units.append({'id':f"{packet['trial_id']}/{claim['question_id']}/sentence-{n}",'text':sentence,'kind':'warrant_sentence'})
  for n,unknown in enumerate(claim['unknowns'],1):
   units.append({'id':f"{packet['trial_id']}/{claim['question_id']}/unknown-{n}",'text':unknown,'kind':'retained_uncertainty'})
  for n,counter in enumerate(claim['counterevidence'],1):
   units.append({'id':f"{packet['trial_id']}/{claim['question_id']}/counter-{n}",'text':counter,'kind':'counterevidence'})
write('private-scoring-units.json',units)
cfg=tomllib.loads((HOME/'config.toml').read_text());assert (cfg['model'],cfg['model_reasoning_effort'])==('gpt-6-luna','medium')
assert not cfg.get('mcp_servers') and all(v is False for v in cfg['features'].values())
assert (WORK/'instructions.md').read_text()==(ROOT/'docs/evaluation/2026-10-04-citation-fidelity-response/instructions.md').read_text()
write('preparation.json',{'all_claims_preserved':len(claim_receipts),'claims':claim_receipts,'cited_spans':len(windows),'private_scoring_units':len(units),'bytes':len(input_text.encode()),'characters':len(input_text),'heuristic_tokens_panel_ratio':round(len(input_text.encode())*16807/36572),'heuristic_tokens_characters_div4':round(len(input_text)/4),'token_count_warning':'Sizing heuristics only; actual input telemetry will be reported.','source_bundle_hashes':protected,'operator_selected_clauses':False,'repair_sources_added':False,'credentials_read_or_copied':False})
write('manifest.json',{'model':'gpt-6-luna','reasoning_effort':'medium','codex_version':subprocess.check_output(['codex','--version'],text=True).strip(),'base_sha':'d6bdae597e72d4ff6221bc2dc65aa1e44fc4ea2f','authorization':'One full-Domain factual feasibility response, two supplied domains, zero tools,3k output,300s wall,120s idle,no retry. Parent01a0fae8-209c-74b0-bd95-43be086b40e3. No assessment continuation.','limits':{'calls':1,'responses_per_arm':1,'tools':0,'output_tokens_per_arm':3000,'wall_seconds_per_arm':300,'idle_seconds_per_arm':120,'input_telemetry_only':True},'instructions_sha256':sha(WORK/'instructions.md'),'private_criteria_sha256':sha(R/'private-criteria.md'),'scoring_units_sha256':sha(R/'private-scoring-units.json'),'exporter_sha256':sha(ROOT/'scripts/export_factual_audit.py'),'arms':{'panel':{'work':str(WORK),'config_sha256':sha(HOME/'config.toml'),'input_sha256':sha(R/'panel-input.txt'),'evidence_manifest_sha256':sha(R/'panel-evidence-manifest.json')}},'existing_rollout_hashes':{str(p):sha(p) for p in (HOME/'sessions').rglob('*.jsonl')},'protected_bundle_hashes':protected,'runner_sha256':sha(R/'run_once.py'),'credentials_read_or_copied':False})
print(json.dumps({'claims':len(claim_receipts),'spans':len(windows),'scoring_units':len(units),'bytes':len(input_text.encode()),'panel_scaled_input_tokens':round(len(input_text.encode())*16807/36572)}))
