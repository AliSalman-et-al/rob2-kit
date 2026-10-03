"""Offline preparation only. This file has no inference launch path."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
import pymupdf
R=Path(__file__).resolve().parent
B=Path('/home/ali/Documents/Code/rob2-kit-benchmark/rob2-meta-set-full-2026-09-29/trials/exscel')
P=R/'next-real-source';P.mkdir(exist_ok=True)
sha=lambda b:hashlib.sha256(b).hexdigest()
known={'NEJMoa1612917.pdf':'b9b1adb69702e20d68d4d98dac57e07cfeb3b73ff014d69a62f8859b200f1121','nejmoa1612917_appendix.pdf':'df91cb4fa3fa0223497f3b828b3c2645f75a8a82d41b91b7e6f96b7e02f08a16','nejmoa1612917_protocol.pdf':'d3498516286f49f1d609124999be3d44a7a8ddac46eb70d4542395ffabcc96a2'}
windows={'NEJMoa1612917.pdf':[3,4,6,8],'nejmoa1612917_appendix.pdf':[31,36,45],'nejmoa1612917_protocol.pdf':[77,78,187,188]}
manifest={'status':'offline_preparation_only_not_launch_ready_not_authorized','question':'Can the host ground a D3.1 availability and material-impact warrant in the actual endpoint-specific evidence, while distinguishing informative accounting from exact observed participant counts?','task_scope':'D3.1 only; no domain label, preferred clinical answer or frozen assessment update','source_directory':str(B),'sources':[],'required_images':[],'projection':'Fresh PyMuPDF text lines; physical PDF pages. These are not original assessment receipt line coordinates.','future_requirements':['A new bounded decision is required before inference.','Choose exact runtime/launcher and source delivery before freezing actual model input.','Use source-completeness preflight covering all eleven full-page texts and both required figure images.','Do not supply private evaluation questions to model.','Verify selected target and numerical result; preserve registry intake conflict separately.','Record actual model receipt of figure images; if transport fails, stop without silently replacing evidence.']}
for name,pages in windows.items():
 raw=(B/name).read_bytes();assert sha(raw)==known[name];doc=pymupdf.open(B/name)
 for page in pages:
  text=doc[page-1].get_text();lines=text.splitlines();label=name+':physical-page-'+str(page)
  entry={'source_identity':'sha256:'+known[name],'file':name,'page':page,'start_line':1,'end_line':len(lines),'projection_sha256':sha(text.encode()),'text_file':name+'-page-'+str(page)+'.txt'}
  (P/entry['text_file']).write_text('\n'.join(f'{i+1}: {line}' for i,line in enumerate(lines))+'\n');manifest['sources'].append(entry)
  if name=='nejmoa1612917_appendix.pdf' and page in [31,45]:
   pix=doc[page-1].get_pixmap(matrix=pymupdf.Matrix(1.5,1.5));png=pix.tobytes('png');filename='appendix-page-'+str(page)+'.png';(P/filename).write_bytes(png);manifest['required_images'].append({'source_identity':'sha256:'+known[name],'page':page,'file':filename,'png_sha256':sha(png),'width':pix.width,'height':pix.height})
f=json.loads((R.parent/'2026-10-03-exscel-host-recovery/frozen-final-state.json').read_text());target=f['proposal']['payload']['results'][0]
(P/'selected-result.json').write_text(json.dumps(target,indent=2)+'\n')
manifest['selected_result_sha256']=sha((P/'selected-result.json').read_bytes());manifest['result_identity']=f['snapshots']['exscel']['result_identity'];manifest['reference_scope_conflict']='Intake NCT01455896 versus article NCT01144338; no silent reconciliation or human gold assumption.'
(P/'manifest-draft.json').write_text(json.dumps(manifest,indent=2)+'\n')
(P/'README.md').write_text('''# Offline preparation for a possible real-source D3.1 check

No model launch occurred and no future call is authorized here. This packet preserves eleven complete primary PDF pages and required Figure S2/S9 images from the original Code benchmark EXSCEL dossier, with recomputed original PDF hashes and exact new projection/image identities. It retains the frozen selected result verbatim. Main pages supply endpoint, assignment analysis, event scale, actual follow-up and the sensitivity-results pointer; appendix pages distinguish endpoint/vital-status flows, treatment-cessation reasons and actually reported sensitivity results; protocol/SAP pages distinguish follow-up procedures, censoring and the tipping-point plan from performed results.

These texts use newly extracted PyMuPDF line numbers, explicitly different from historical read-receipt coordinates. Figures require actual image delivery, not merely blank extracted text. The future input and source-completeness manifest must be frozen only after a new bounded decision chooses the precise delivery mechanism. This is preparation, not a passed launch preflight.

Private evaluation focus: does the host explain what endpoint-specific temporal coverage, the 541 non-completers without a recorded first event, 1,744 recorded first-event participants, and actual follow-up pathways imply about plausible material effect on the selected HR, without asserting a participant-observation fraction or insisting on a formal HR bound? Does it distinguish recorded absence of a first event from unknown future first events, and the SAP plan from reported performed sensitivities? NI remains permissible if warranted. No preferred answer or domain label is a success criterion, and no label should be changed in the frozen assessment.
''')
print('Prepared eleven real-source pages and two figures offline; no launch path.')
