from pathlib import Path
import json,sqlite3,subprocess,os
root=Path('../diagnostics/frozen-exscel-bd92ec8').resolve()
with sqlite3.connect(f'file:{root}/workspace/.rob2-kit/canonical.sqlite3?mode=ro',uri=True) as c:s=json.loads(c.execute('select payload from workflow_head').fetchone()[0])
review='sha256:c8091d311b549d5d26848195814279c93f2ce1e8ef2b9709bcf692c91c7a4a66';proposal='sha256:28982d105319fc9fddb2b437f6ffbac041a811e0b2fc209ea1213202ee4aba5d'
assert (s['phase'],s['revision'],s['review']['identity'],s['proposal']['identity'])==('proposal',3,review,proposal)
assert not s.get('proposal_acknowledgment') and not s.get('domain_records')
auth={'review_identity':review,'proposal_identity':proposal,'delegated_recording':True,'independent_human_adjudication':False,'source_thread_id':'01a0fae8-209c-74b0-bd95-43be086b40e3','assistant_scope_request_message':'Sentinel_60cc226eb404819196a0095a1763306a','assistant_scope_request':'Approve this scope for the single-case evaluation? EXSCEL exenatide2mgweekly vsplacebo/allrandomized/firstCVdeath,nonfatalMI,nonfatalstroke/trialfollowup/HR0.91 CI0.83-1.00; articleNCT01144338,conflictingmetadata preserved; supplementdefinitions compatible but agentmustread.','explicit_approval':{'message_id':'Sentinel_78073e975f34819187a70a3cd3344979','author':'Ali','timestamp':'2026-10-03 13:08 UTC','text':'Yes'},'standing_authority':{'message_id':'Sentinel_2126a58e9a608191b6fcfb6c175f00e4','author':'Ali','timestamp':'2026-10-03 13:08 UTC','text':"Like I said, you have my approval do as you deem reasonable to further our goal of optimizing rob2-kit. Don't wait on me."}}
(root/'written-approval-authorization.json').write_text(json.dumps(auth,indent=2)+'\n')
command=['/home/ali/Documents/Codex/2026-10-02/task/rob2-kit/.venv/bin/python','-m','rob2_kit.interfaces.cli.app','review','--workspace',str(root/'workspace'),'--review-reference',review]
result=subprocess.run(command,input='yes\n',text=True,capture_output=True,env={**os.environ,'PYTHONPATH':str(root.parent/'frozen-exscel-bd92ec8-code/src')},check=True)
(root/'cli-acknowledgment.stdout').write_text(result.stdout);(root/'cli-acknowledgment.stderr').write_text(result.stderr)
with sqlite3.connect(f'file:{root}/workspace/.rob2-kit/canonical.sqlite3?mode=ro',uri=True) as c:after=json.loads(c.execute('select payload from workflow_head').fetchone()[0])
assert after['phase']=='assessment' and after['proposal_acknowledgment']['review_identity']==review and after['proposal_review']['identity']==review
(root/'approved-seed-state.json').write_text(json.dumps(after,indent=2)+'\n');print('Delegated CLI acknowledged exact Ali-approved Review; phase',after['phase'],'revision',after['revision'])
