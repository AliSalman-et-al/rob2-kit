from pathlib import Path
import sys,json,subprocess,shutil,hashlib,tomllib
repo=Path('/home/ali/Documents/Codex/2026-10-02/task-4/rob2-kit');sys.path.insert(0,str(repo/'src'))
from rob2_kit.packs import SCIENTIFIC_PACK
root=repo.parent/'diagnostics/tool-free-observation-pair-e6b893b';root.mkdir(exist_ok=True)
assert not subprocess.check_output(['git','status','--porcelain'],cwd=repo)
sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip();assert sha.startswith('e6b893b')
questions=[q for q in SCIENTIFIC_PACK.questions if q.id in ['sq:deviations:appropriate-analysis','sq:missing:data-available','sq:missing:true-value-dependent','sq:missing:likely-dependent']]
guidance=[{'question_id':q.id,'wording':q.wording,'options':[a.value for a in q.allowed_answers],'guidance':q.guidance.model_dump(mode='json') if q.id=='sq:missing:likely-dependent' else {'official':q.guidance.official.model_dump(mode='json'),'operational':{k:v for k,v in q.guidance.operational.model_dump(mode='json').items() if k in ['decision_rule','evidence_needed','no_information_rule']}}} for q in questions]
base='''This is an explicitly synthetic scientific mechanism contrast, not a factual reconstruction of a clinical trial. Its rescue/analysis pattern is motivated by a retained trial article and supplement; endpoint-collection facts below are synthetic controls.
Assessment target: effect of assignment, experimental treatment versus control, change in a glycemic endpoint at the prespecified terminal visit among all randomized participants.
Report: Additional treatment was triggered by sustained high glucose; investigator discretion also used recent glycemic measurements. A larger proportion of control participants received this treatment than experimental participants. Participants receiving additional treatment remained scheduled for terminal measurement. The efficacy analysis used only measurements before additional treatment, with last observation carried forward when the terminal analysis value was unavailable.
OBSERVATION_FACT
Report: A separate subgroup stopped assigned study medication. The report does not state whether that subgroup's terminal measurements were obtained, or why they might be unavailable. No subgroup counts or complete randomized-population ascertainment total are supplied.
Use only these source statements and the current production guidance below. In at most 600 words, explain the implications for assignment-analysis appropriateness and signalling questions 3.1, 3.3 and 3.4. Give question responses only when the stated scope supports them; distinguish subgroup facts from the whole Result. Do not invent missing facts or supply a domain/overall risk label. State the material uncertainties and the source fact on which any dependence reasoning rests. No tools, outside knowledge, coding or follow-up requests.
Current production guidance:
'''+json.dumps(guidance,ensure_ascii=False,separators=(',',':'))
conditions={'condition_a':'Report: Terminal endpoint measurements after additional treatment were obtained for all such participants.','condition_b':'Report: Terminal endpoint measurements after additional treatment were not obtained for any such participants.'}
prior=repo.parent/'diagnostics/frozen-award1-d3-repair4'
for name,fact in conditions.items():
 p=root/name;p.mkdir(exist_ok=True);(p/'workspace').mkdir(exist_ok=True);(p/'home').mkdir(exist_ok=True)
 for f in ['auth.json','models_cache.json']:shutil.copyfile(prior/'home'/f,p/'home'/f)
 config=(prior/'home/config.toml').read_text().split('[mcp_servers.rob2]')[0]
 config=config.replace(str(prior/'instructions.md'),str(p/'instructions.md'))
 config+='code_mode = {enabled=false}\n'
 (p/'home/config.toml').write_text(config)
 (p/'instructions.md').write_text('Analyze the supplied synthetic scientific excerpts using the supplied guidance. Produce one final response, at most 600 words. Do not use tools or outside sources. No follow-up, coding, or extra response.\n')
 prompt=base.replace('OBSERVATION_FACT',fact);(p/'prompt.txt').write_text(prompt)
 conf=tomllib.loads(config);assert 'mcp_servers' not in conf and conf['model']=='gpt-6-luna' and conf['model_reasoning_effort']=='medium'
 assert conf['features']['code_mode']['enabled'] is False
 # UTF-8 byte length is a conservative token upper bound for the ASCII-heavy prompt;
 # reserve another 2k for fixed host instructions and protocol overhead.
 bound=len(prompt.encode())+2000;assert bound<20000
 (p/'manifest.json').write_text(json.dumps({'condition':name,'code_sha':sha,'model':'gpt-6-luna','effort':'medium','prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'preflight_input_token_upper_bound':bound,'max_words':600,'wall_seconds':480,'idle_seconds':120,'one_response_only':True,'tool_free':True,'synthetic':True,'no_retry':True},indent=2)+'\n')
(root/'design.json').write_text(json.dumps({'code_sha':sha,'conditions':conditions,'single_changed_fact':'Terminal endpoint measurements obtained versus not obtained after the same outcome-driven treatment change.','fixed_unknown_control':'Separate drug discontinuers have unspecified endpoint collection status and reasons.','source_basis':'Code AWARD-1 article pre-rescue efficacy handling and supplemental glucose-linked rescue; terminal observation facts are explicitly synthetic because actual source status was not established.','guidance':guidance,'no_gold_risk_labels':True,'max_invocations':2,'max_responses_per_condition':1},indent=2)+'\n')
print('Prepared two tool-free synthetic prompts; upper bounds',[(x.name,json.loads((x/'manifest.json').read_text())['preflight_input_token_upper_bound']) for x in root.iterdir() if x.is_dir()])
