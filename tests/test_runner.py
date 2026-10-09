import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from filsat_runner.files import safe_file,deliverables,make_prompt,download_inputs
from filsat_runner.adapters import command_for,environment,event_stage
from filsat_runner.http import Client
from filsat_runner.worker import Worker
from filsat_runner.readiness import Readiness
from filsat_runner.processes import ProcessTree
import subprocess
import sys

class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        (self.root/'outputs').mkdir(); (self.root/'inputs').mkdir()
    def tearDown(self): self.temp.cleanup()
    def test_paths_cannot_escape_or_reference_credentials(self):
        for name in ('../token.txt','/tmp/key.txt','C:/key.txt','x\\key.txt','.env'):
            with self.assertRaises(ValueError): safe_file(self.root/'outputs',name)
    def test_symlinks_are_rejected(self):
        target=self.root/'private.txt'; target.write_text('secret')
        link=self.root/'outputs'/'result.txt'
        try: link.symlink_to(target)
        except OSError: self.skipTest('Symlink permission unavailable')
        with self.assertRaises(ValueError): safe_file(self.root/'outputs','result.txt')
    def test_output_directory_link_is_rejected(self):
        external=self.root/'external'; external.mkdir(); (external/'secret.txt').write_text('secret')
        link=self.root/'linked'
        try: link.symlink_to(external,target_is_directory=True)
        except OSError: self.skipTest('Symlink permission unavailable')
        with self.assertRaises(ValueError): safe_file(link,'secret.txt')
    def test_readiness_requires_actual_response_and_caches_it(self):
        health=Readiness(self.root); config={'kind':'codex'}
        with patch('filsat_runner.readiness.adapters.run',return_value='FILSAT_READY') as run:
            self.assertTrue(health.check(config)); self.assertTrue(health.check(config)); self.assertEqual(run.call_count,1)
        health.invalidate(config)
        with patch('filsat_runner.readiness.adapters.run',return_value='Authentication failed'):
            self.assertFalse(health.check(config))
    def test_n8n_requires_workflow_acknowledgment_and_health(self):
        health=Readiness(self.root)
        with patch('filsat_runner.readiness.request',return_value={'status':'ok'}):
            self.assertFalse(health.check({'kind':'n8n','url':'http://localhost:5678/webhook/test'}))
            self.assertTrue(health.check({'kind':'n8n','url':'http://localhost:5678/webhook/test','workflow_ready':True}))
    def test_process_containment_runs_and_stops_provider(self):
        tree=ProcessTree(); proc=None
        try:
            proc=tree.spawn([sys.executable,'-c','import time; print("ready",flush=True); time.sleep(60)'],stdout=subprocess.PIPE,text=True)
            self.assertEqual(proc.stdout.readline().strip(),'ready')
        finally:
            tree.close(proc)
            if proc is not None: proc.stdout.close()
        self.assertIsNotNone(proc.poll())
    def test_valid_manifest_only_exports_explicit_files(self):
        (self.root/'outputs'/'result.txt').write_text('ok')
        (self.root/'outputs'/'internal.txt').write_text('private')
        (self.root/'result.json').write_text(json.dumps({'text':'Done','files':['result.txt']}))
        text,files=deliverables(self.root)
        self.assertEqual(text,'Done'); self.assertEqual([p.name for p in files],['result.txt'])
    def test_invalid_and_duplicate_manifests_fail(self):
        (self.root/'outputs'/'a.txt').write_text('a')
        for result in ({'text':'','files':[]},{'text':'ok','files':['a.txt','a.txt']},{'text':'ok','files':['missing.txt']}):
            (self.root/'result.json').write_text(json.dumps(result))
            with self.assertRaises(ValueError): deliverables(self.root)
    def test_provider_environment_does_not_inherit_site_token(self):
        with patch.dict(os.environ,{'FILS'+'AT_TOKEN':'secret','UNRELATED_SECRET':'no','TEST_PROVIDER_KEY':'yes'}):
            env=environment({'env_names':['TEST_PROVIDER_KEY','FILS'+'AT_TOKEN']})
            self.assertNotIn('FILS'+'AT_TOKEN',env); self.assertNotIn('UNRELATED_SECRET',env)
            self.assertEqual(env['TEST_PROVIDER_KEY'],'yes')
    def test_codex_command_keeps_sandbox_and_uses_stdin(self):
        with patch('filsat_runner.adapters.executable',return_value=['codex']):
            cmd=command_for({'kind':'codex'},self.root)
        self.assertIn('workspace-write',cmd); self.assertIn('--ignore-user-config',cmd); self.assertEqual(cmd[-1],'-')
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox',cmd)
    def test_progress_only_from_known_events(self):
        self.assertEqual(event_stage({'item':{'type':'web_search'}}),'searching')
        self.assertIsNone(event_stage({'type':'secret_reasoning_text','text':'I am searching'}))
    def test_job_prompt_does_not_expose_transport_secrets(self):
        prompt=make_prompt({'input':'Draw a tree','lease':'secret','token':'credential'},[])
        self.assertNotIn('credential',prompt.split('Service contract and customer data (JSON):')[1]); self.assertNotIn('secret',prompt.split('Service contract and customer data (JSON):')[1])
    def test_remote_site_requires_https(self):
        with self.assertRaises(ValueError): Client('http://example.com','token')
        with self.assertRaises(ValueError): Client('https://user:pass@example.com','token')
    def test_input_checksums_are_enforced(self):
        class Fake:
            def call(self,*a,**kw): return b'altered'
        job={'id':'job','lease':'lease','files':[{'id':'00000000-0000-0000-0000-000000000000','name':'a.txt','size':2,'sha256':hashlib.sha256(b'ok').hexdigest()}]}
        with self.assertRaises(ValueError): download_inputs(Fake(),job,self.root)
    def test_worker_refuses_unsandboxed_runtime_without_isolation_acknowledgment(self):
        with self.assertRaises(ValueError): Worker({'services':{'1':{'kind':'pi'}}},self.root)

if __name__=='__main__': unittest.main()
