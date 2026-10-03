"""Verify report, reusable tools and technical collaboration records."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if sys.flags.optimize:raise SystemExit('Run without -O')
    folder=ROOT/'report/ai_records'
    integrity=read(folder/'integrity.json')
    for name,digest in integrity['sha256'].items():
        path=(folder/name).resolve()
        if not path.is_relative_to(folder) or sha(path)!=digest:raise RuntimeError(('changed AI attachment',name))
    rows=[json.loads(x) for x in (folder/'dialogue.jsonl').read_text(encoding='utf-8').splitlines()]
    if len(rows)!=23 or len({r['source_line'] for r in rows})!=23:raise RuntimeError('AI excerpt count')
    for row in rows:
        if row['role'] not in ['user','assistant']:raise RuntimeError('unexpected dialogue role')
        if row['role']=='assistant' and row['phase'] not in ['commentary','final_answer']:raise RuntimeError('unexpected assistant phase')
        if hashlib.sha256(row['text'].encode()).hexdigest()!=row['excerpt_sha256']:raise RuntimeError('excerpt text mismatch')
        start,end=row['excerpt_span']
        if start<0 or end-start!=len(row['text']):raise RuntimeError('excerpt span mismatch')
    for entry in read(folder/'artifact_excerpts.json'):
        p=ROOT/entry['path']
        if sha(p)!=entry['file_sha256']:raise RuntimeError(('artifact source changed',entry['path']))
        lines=p.read_text(encoding=entry['encoding']).splitlines()
        for row in entry['lines']:
            if lines[row['line']-1]!=row['text']:raise RuntimeError(('artifact excerpt changed',entry['id']))
    report=ROOT/'report/design_report.docx'
    with zipfile.ZipFile(report) as archive:
        root=ET.fromstring(archive.read('word/document.xml'))
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        text=''.join(x.text or '' for x in root.findall('.//w:t',ns))
        for word in ['0000A501','41.51','1704']:
            if word not in text:raise RuntimeError(('missing report result',word))
        if root.findall('.//w:pBdr',ns):raise RuntimeError('unexpected paragraph border')
    info=read(ROOT/'report/submission_info.json')
    if not info.get('anonymous'):raise RuntimeError('not an anonymous submission')
    for key in ['school','advisor','leader','members','team_name','team_number']:
        if info.get(key):raise RuntimeError(('identity field is not empty',key))
    for document in ['report/design_report.docx','report/figures/system_diagrams.vsdx']:
        with zipfile.ZipFile(ROOT/document) as archive:
            core=ET.fromstring(archive.read('docProps/core.xml'))
            for prop in core:
                if prop.tag.rsplit('}',1)[-1] in ['creator','lastModifiedBy'] and (prop.text or '').strip():
                    raise RuntimeError(('personal document property',document))
    if not (ROOT/'report/design_report.pdf').read_bytes().startswith(b'%PDF-'):raise RuntimeError('missing PDF')
    with zipfile.ZipFile(ROOT/'report/figures/system_diagrams.vsdx') as z:
        if z.testzip() is not None:raise RuntimeError('Visio container checksum')
        pages=ET.fromstring(z.read('visio/pages/pages.xml'))
        if len(pages)!=3:raise RuntimeError('Visio page count')
    qa=read(ROOT/'report/document_validation.json')
    if qa['page_count']!=26 or qa['visually_inspected_pages']!=list(range(1,27)):raise RuntimeError('report visual review incomplete')
    for name,digest in qa['sha256'].items():
        if sha(ROOT/name)!=digest:raise RuntimeError(('document changed after visual review',name))
    for script,args in [('run_examples.py',[]),('project_adapter.py',[ROOT])]:
        r=subprocess.run([sys.executable,'-B','-X','utf8',str(ROOT/'skill/scripts'/script),*map(str,args)],
                         capture_output=True,text=True,encoding='utf-8')
        if r.returncode:raise RuntimeError(r.stdout+r.stderr)
        result=json.loads(r.stdout)
        if result['status']!='PASS':raise RuntimeError(result)
        if script=='run_examples.py' and result['checks']!=15:raise RuntimeError('example count')
        print('PASS: skill',script,flush=True)
    print('PASS: formal report, three editable Visio pages, 23 visible technical excerpts, exact failure/correction excerpts.')
    print('PASS: material verification complete.')


if __name__=='__main__':main()
