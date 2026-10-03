"""Independent hand-calculated fixtures and fault injection; no FPGA connection."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def jsonl(path, rows):
    path.write_text(''.join(json.dumps(x, ensure_ascii=False)+'\n' for x in rows), encoding='utf-8')


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix='fpga_audit_example_') as temp:
        root = Path(temp)
        # Gold results are fixed arithmetic, independent of the audit implementation.
        inputs = [dict(a=[2,-3,4], b=[5,6,-2]), dict(x=[1,2,3,4], taps=[1,-1,2])]
        expected = [dict(case_id='signed_dot', input_sha256=hashlib.sha256(json.dumps(inputs[0],sort_keys=True).encode()).hexdigest(), result=-16),
                    dict(case_id='fir_valid', input_sha256=hashlib.sha256(json.dumps(inputs[1],sort_keys=True).encode()).hexdigest(), result=[3,5])]
        observed = [dict(x, build_id='example_v1') for x in expected]
        gold, actual = root/'expected.jsonl', root/'observed.jsonl'
        jsonl(gold, expected); jsonl(actual, observed)

        def check(name, args, success, expected_fragment=None):
            run = subprocess.run([sys.executable,'-B',str(HERE/'audit.py'),*map(str,args)], capture_output=True,text=True,encoding='utf-8')
            result = json.loads(run.stdout)
            if (run.returncode == 0) != success or result['status'] != ('PASS' if success else 'FAIL'):
                raise RuntimeError((name,run.returncode,run.stdout,run.stderr))
            if expected_fragment and expected_fragment not in result.get('error',''):
                raise RuntimeError((name,'wrong diagnostic',result))
            results.append(dict(test=name, expected='PASS' if success else 'REJECT', actual=result))
            return result

        compare_args=['compare',gold,actual,'--build-id','example_v1']
        check('two_tasks_dot_and_fir', compare_args, True)
        for name, rows, fragment in [
            ('wrong_integer', [dict(observed[0], result=-15), observed[1]], 'result mismatch'),
            ('missing_case', observed[:1], 'case set mismatch'),
            ('duplicate_case', observed+[observed[0]], 'duplicate case_id'),
            ('wrong_build', [dict(observed[0],build_id='old'),observed[1]], 'build_id mismatch'),
            ('different_input', [dict(observed[0],input_sha256='0'*64),observed[1]], 'input mismatch'),
            ('float_disguised_integer', [dict(observed[0],result=-16.0),observed[1]], 'exact integers'),
            ('boolean_disguised_integer', [dict(observed[0],result=True),observed[1]], 'exact integers')]:
            jsonl(actual,rows);check(name,compare_args,False,fragment)
        jsonl(actual,observed)
        manifest=root/'manifest.json'
        dump(manifest,dict(sha256={'observed.jsonl':hashlib.sha256(actual.read_bytes()).hexdigest()}))
        check('unchanged_file', ['files',root,manifest],True)
        actual.write_bytes(actual.read_bytes()+b' ')
        check('tampered_file', ['files',root,manifest],False,'hash mismatch')
        dump(manifest,dict(sha256={'../escape.txt':'0'*64}))
        check('manifest_path_escape',['files',root,manifest],False,'unsafe relative path')
        identity=dict(task='fir_valid',case_id='fir_valid',input_sha256=expected[1]['input_sha256'],build_id='example_v1',clock_hz=1000000,boundary='board_full_task')
        trials=[dict(identity,mode=m,cycles=c) for m,values in [('cpu',[990,1000,1010]),('accelerator',[240,250,260])] for c in values]
        timing_file=root/'timing.json';dump(timing_file,dict(trials=trials))
        report=check('same_task_timing',['timing',timing_file],True)
        if report['speedup'] != 4 or report['median_ms'] != {'cpu':1.0,'accelerator':0.25}:
            raise RuntimeError('incorrect median/units')
        bad=copy.deepcopy(trials);bad[-1]['input_sha256']='1'*64;dump(timing_file,dict(trials=bad))
        check('mixed_input_timing',['timing',timing_file],False,'unfair timing')
        bad=copy.deepcopy(trials);bad[-1]['boundary']='core_only';dump(timing_file,dict(trials=bad))
        check('core_as_full_timing',['timing',timing_file],False,'unfair timing')
        dump(timing_file,dict(trials=trials[:3]))
        check('missing_cpu_or_accelerator',['timing',timing_file],False,'both cpu and accelerator')
    print(json.dumps(dict(status='PASS', physical_board=False, description='two hand-calculated tasks; synthetic transport and timing fixtures',
                         checks=len(results), results=results),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
