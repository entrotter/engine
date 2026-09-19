import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from entrotter_engine.api import EngineServer

class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.server=EngineServer(0,token='test-only',output=cls.temp.name)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.fixture=json.loads((Path(__file__).parent/'data/fixture.json').read_text())
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.temp.cleanup()
    def request(self,method,path,body=None,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        h={'Authorization':'Bearer test-only','Content-Type':'application/json'};h.update(headers or {})
        c.request(method,path,json.dumps(body) if body is not None else None,h)
        r=c.getresponse();status=r.status;data=json.loads(r.read());c.close();return status,data
    def test_health(self): self.assertEqual(self.request('GET','/health')[0],200)
    def test_auth(self): self.assertEqual(self.request('GET','/health',headers={'Authorization':'Bearer wrong'})[0],401)
    def test_dns_rebinding_guard(self): self.assertEqual(self.request('GET','/health',headers={'Host':'attacker.invalid'})[0],403)
    def test_browser_request_rejected(self): self.assertEqual(self.request('POST','/v1/runs',self.fixture,{'Origin':'https://attacker.invalid'})[0],403)
    def test_roundtrip(self):
        status,result=self.request('POST','/v1/runs',self.fixture);self.assertEqual(status,201)
        status,again=self.request('GET','/v1/runs/'+result['artifact_id']);self.assertEqual(status,200);self.assertEqual(result,again)
    def test_invalid_scenario(self): self.assertEqual(self.request('POST','/v1/runs',{})[0],400)
    def test_missing_report(self): self.assertEqual(self.request('GET','/v1/runs/'+'a'*64)[0],404)
    def test_path_traversal(self): self.assertEqual(self.request('GET','/v1/runs/../../etc/passwd')[0],404)
    def test_concurrency_limit(self):
        self.server.slot.acquire()
        try: self.assertEqual(self.request('POST','/v1/runs',self.fixture)[0],429)
        finally: self.server.slot.release()
    def test_content_type(self): self.assertEqual(self.request('POST','/v1/runs',{}, {'Content-Type':'text/plain'})[0],415)
    def test_payload_limit(self):
        # The server rejects the declared size before reading bytes. Sending a
        # large body races that close and can reset the client's write on macOS.
        self.assertEqual(self.request('POST','/v1/runs',headers={'Content-Length':'270000'})[0],413)

if __name__=='__main__': unittest.main()
