"""Loopback-only application demo using actual frozen A501 board calculations."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import threading
import application_preamble as app

DEMOS = [
 ('core_q4_s6_r00','四条短报文 · 正文、噪声与不同幅度'),
 ('core_q1_s6_r00','一条短报文 · 查找开头'),
 ('core_q2_s6_r00','两条短报文 · 分别定位'),
 ('negative_payload_000','普通随机数据 · 没有目标前导码'),
 ('negative_other_000','另一种前导序列 · 非目标报文'),
 ('stress_snr_l0_r00','很弱的报文 · −6 dB 边界'),
 ('stress_dc_l4_r00','较大直流偏置 · 退化边界'),
 ('boundary_similar_00','形似前导码的序列 · 误报边界'),
 ('boundary_cross_0_0','前导码跨数据块 · 范围边界'),
]


def main():
    p=argparse.ArgumentParser();p.add_argument('--port',default='COM9');p.add_argument('--http-port',type=int,default=8767);args=p.parse_args()
    cases={c['id']:c for c in app.load_cases()};allowed_ids={name for name,label in DEMOS}
    hosts={f'127.0.0.1:{args.http_port}',f'localhost:{args.http_port}'};busy=threading.Lock()
    names=['index.html','app.js','style.css','snr_curve.svg','dc_curve.svg','amplitude_curve.svg',
           'application_groups.csv','core_groups.csv','stress.csv','performance.csv']
    files={'/':'index.html',**{'/'+x:x for x in names}}
    class Handler(BaseHTTPRequestHandler):
        def respond(self,status,body,kind='application/json; charset=utf-8'):
            if not isinstance(body,bytes):body=json.dumps(body,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
        def do_GET(self):
            if self.headers.get('Host') not in hosts:self.respond(403,{'error':'Local host required'});return
            if self.path=='/api/config':
                self.respond(200,dict(application='preamble',build_id=app.BUILD,port=args.port,
                    busy=(app.ROOT/'board/results/.detection_a3_serial.lock').exists(),cases=[dict(id=i,label=t) for i,t in DEMOS]));return
            if self.path=='/api/report':
                path=app.REPORT/'metrics.json';self.respond(200,app.read(path) if path.exists() else dict(status='PENDING'));return
            name=files.get(self.path)
            base=app.ROOT/'src/host/web' if name in ['index.html','app.js','style.css'] else app.REPORT
            if name is None or not (base/name).is_file():self.respond(404,{'error':'Not found'});return
            kind=mimetypes.guess_type(name)[0] or 'application/octet-stream'
            if name.endswith('.js'):kind='text/javascript'
            self.respond(200,(base/name).read_bytes(),kind+('; charset=utf-8' if kind.startswith('text/') else ''))
        def do_POST(self):
            origin=self.headers.get('Origin')
            if self.headers.get('Host') not in hosts or (origin and origin not in {'http://'+h for h in hosts}):
                self.respond(403,{'error':'Local origin required'});return
            if self.path not in ['/api/preview','/api/run']:self.respond(404,{'error':'Not found'});return
            try:
                n=int(self.headers.get('Content-Length','0'))
                if not 0<n<=512 or self.headers.get_content_type()!='application/json':raise ValueError()
                data=json.loads(self.rfile.read(n))
                if set(data)!={'case_id'} or data['case_id'] not in allowed_ids:raise ValueError()
            except (ValueError,TypeError):self.respond(400,{'error':'请选择列表中的演示场景。'});return
            if self.path=='/api/preview':self.respond(200,cases[data['case_id']]);return
            if (app.ROOT/'board/results/.detection_a3_serial.lock').exists() or not busy.acquire(blocking=False):
                self.respond(409,{'error':'板卡正在测试，请等待当前任务完成。'});return
            try:
                out,_=app.run('demo',args.port,data['case_id'])
                result=app.read(out/'demo.json');app.a5.dump(app.REPORT/'last_demo.json',result);self.respond(200,result)
            except Exception as exc:
                print('DEMO FAIL:',exc,flush=True)
                self.respond(503,{'error':'本次实板计算未通过，请检查供电、PL_UART 和板上程序；原始记录已保留。'})
            finally:busy.release()
    server=ThreadingHTTPServer(('127.0.0.1',args.http_port),Handler)
    print(f'Preamble demo: http://127.0.0.1:{args.http_port} serial={args.port} build={app.BUILD}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
