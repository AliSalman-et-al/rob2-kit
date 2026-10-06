"""One local pass-through HTTP capture; no header/auth persistence or payload repair."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import json,sys,gzip,threading
import httpx
root=Path(sys.argv[1]); lock=threading.Lock(); ordinal=0
class Handler(BaseHTTPRequestHandler):
 protocol_version='HTTP/1.1'
 def log_message(self,*args):pass
 def do_GET(self): self.forward()
 def do_POST(self): self.forward()
 def forward(self):
  global ordinal
  body=self.rfile.read(int(self.headers.get('content-length',0)))
  decoded=gzip.decompress(body) if self.headers.get('content-encoding')=='gzip' else body
  if self.command=='POST' and '/responses' in self.path:
   try: payload=json.loads(decoded)
   except Exception:
    (root/'host-seam-stop.json').write_text(json.dumps({'reason':'Request body not inspectable','encoding':self.headers.get('content-encoding')}));self.send_error(400);return
   with lock:
    ordinal+=1
    # Persist only declarations, routing model and size; user input lives in normal rollout.
    tools=payload.get('tools',[])
    (root/f'hosted-tools-{ordinal:02d}.json').write_text(json.dumps({'model':payload.get('model'),'request_bytes':len(body),'tools':tools},indent=2)+'\n')
    proposals=[]
    def visit(value):
     if isinstance(value,dict):
      if 'validate_proposal' in str(value.get('name','')):proposals.append(value)
      for item in value.values():visit(item)
     elif isinstance(value,list):
      for item in value:visit(item)
    visit(tools)
    valid=False
    for proposal in proposals:
     schema=proposal.get('parameters',proposal.get('input_schema',{}))
     props=schema.get('properties',{})
     result=props.get('results',{}).get('items',{})
     missing=props.get('missing_results',{}).get('items',{})
     if result.get('type')=='object' and missing.get('type')=='object' and result.get('required') and missing.get('required') and not any(k in result or k in missing for k in ['anyOf','oneOf']):valid=True
    if not valid:
     (root/'host-seam-stop.json').write_text(json.dumps({'reason':'Hosted request lacks unambiguous nested required proposal collections','request':ordinal,'proposal_declarations_found':len(proposals)},indent=2)+'\n');self.send_error(400);return
  headers={k:v for k,v in self.headers.items() if k.lower() not in {'host','content-length','connection'}}
  try:
   with httpx.Client(timeout=120) as client:
    with client.stream(self.command,'https://chatgpt.com'+self.path,headers=headers,content=body) as response:
     self.send_response(response.status_code)
     for key,value in response.headers.items():
      if key.lower() not in {'transfer-encoding','connection','content-length'}:self.send_header(key,value)
     self.send_header('Connection','close');self.end_headers()
     for chunk in response.iter_raw():self.wfile.write(chunk);self.wfile.flush()
     self.close_connection=True
  except Exception as exc:
   (root/'capture-transport-error.json').write_text(json.dumps({'type':type(exc).__name__}))
   self.close_connection=True
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
(root/'capture-port.txt').write_text(str(server.server_port))
server.serve_forever()
