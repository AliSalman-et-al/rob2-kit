"""Cumulative reactive guards across every resumed turn; never reset at a boundary."""
from __future__ import annotations
import json,os,selectors,signal,subprocess,time
from pathlib import Path
from typing import Any

class Monitor:
    def __init__(self, session_file: Path, *, clock=time.monotonic):
        self.session_file=session_file;self.clock=clock;self.start=self.last=clock()
        self.baseline=self.records();self.new={};self.calls=set();self.domain_saves={}
        self.identical=0;self.previous_error=None;self.stop=None;self.events=[];self.turn_index=0
        self.baseline_wrappers={json.loads(line).get("payload",{}).get("call_id") for line in self.session_file.read_text().splitlines() if json.loads(line).get("type")=="response_item" and json.loads(line).get("payload",{}).get("type")=="custom_tool_call"}
    def records(self):
        rows={}
        for line in self.session_file.read_text().splitlines():
            try:r=json.loads(line)
            except ValueError:continue
            if r.get('type')=='token_usage_record':
                p=r['payload'];rows[p['response_id']]=p
        return rows
    def usage(self):
        self.new={k:v for k,v in self.records().items() if k not in self.baseline}
        return {key:sum(r['usage'].get(key,0) for r in self.new.values()) for key in ['input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens']}
    def consume(self,row):
        self.last=self.clock();self.events.append(row)
        item=row.get('item',{});kind=item.get('type')
        if row.get('type')=='item.started' and kind=='mcp_tool_call':
            self.calls.add(('mcp',f"{self.turn_index}:{item['id']}"))
            if item.get('tool')=='save_domain_judgment':
                domain=item.get('arguments',{}).get('domain_id','unknown')
                self.domain_saves[domain]=self.domain_saves.get(domain,0)+1
        if row.get('type')=='item.completed' and kind=='mcp_tool_call':
            result=item.get('result') or {};data=result.get('structured_content') or {}
            failed=item.get('status')=='failed' or item.get('error') or data.get('outcome') in ['error','condition','repair']
            if failed:
                from domain_probe_controls_telemetry import rejection_fingerprint
                fingerprint=rejection_fingerprint(result)
                self.identical=self.identical+1 if fingerprint==self.previous_error else 1
                self.previous_error=fingerprint
            else:self.identical=0;self.previous_error=None
    def check(self):
        usage=self.usage()
        # Include any durable wrapper calls not represented by direct MCP events.
        for line in self.session_file.read_text().splitlines():
            try:r=json.loads(line)
            except ValueError:continue
            p=r.get('payload',{})
            if r.get('type')=='response_item' and p.get('type')=='custom_tool_call' and p.get('call_id') not in self.baseline_wrappers:
                self.calls.add(('wrapper',p['call_id']))
        tests=[(len(self.calls)>=60,'cumulative tool limit'),(usage['output_tokens']>=12000,'cumulative output limit'),(self.clock()-self.start>=900,'total wall limit'),(self.clock()-self.last>=180,'idle limit'),(self.identical>=2,'repeated identical error'),(any(n>4 for n in self.domain_saves.values()),'per-Domain construction allowance')]
        self.stop=self.stop or next((why for reached,why in tests if reached),None)
        return self.stop
    def invoke(self,command: list[str],prompt: str, *, cwd: Path,env:dict[str,str], trace:Path,stderr:Path):
        if self.check():return 124
        self.turn_index+=1
        with trace.open('wb') as log,stderr.open('wb') as err:
            p=subprocess.Popen(command,cwd=cwd,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,start_new_session=True)
            p.stdin.write(prompt.encode());p.stdin.close();selector=selectors.DefaultSelector();selector.register(p.stdout,selectors.EVENT_READ)
            try:
                while p.poll() is None:
                    for _,_mask in selector.select(1):
                        raw=p.stdout.readline()
                        if raw:
                            log.write(raw);log.flush();self.consume(json.loads(raw))
                    if self.check():break
            finally:
                if p.poll() is None:
                    os.killpg(p.pid,signal.SIGTERM)
                    try:p.wait(timeout=5)
                    except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
                for raw in p.stdout:
                    log.write(raw)
                    if raw.strip():self.consume(json.loads(raw))
                self.check();selector.close()
        return 124 if self.stop else p.returncode
    def summary(self):
        u=self.usage()
        return {'stop':self.stop,'elapsed_seconds':self.clock()-self.start,'calls':len(self.calls),'call_ids':sorted(self.calls),'domain_save_starts':self.domain_saves,'consecutive_identical_errors':self.identical,'usage':u,'uncached_input_tokens':u['input_tokens']-u['cached_input_tokens'],'baseline_response_ids':sorted(self.baseline),'new_response_ids':sorted(self.new),'output_overshoot':max(0,u['output_tokens']-12000),'tool_overshoot':max(0,len(self.calls)-60),'guards_reactive':True}
