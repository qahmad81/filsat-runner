import concurrent.futures
import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from . import adapters
from .files import download_inputs, make_prompt, deliverables
from .http import Client
from .readiness import Readiness

class Worker:
    def __init__(self,config,config_dir):
        self.config=config
        self.services=config['services']
        if not self.services or len(self.services)>100 or any(not str(k).isdigit() for k in self.services):
            raise ValueError('Bind one or more numeric service IDs in services')
        for adapter in self.services.values():
            if adapter.get('kind') not in adapters.KINDS: raise ValueError('Unknown adapter')
            if adapter['kind'] in ('pi','deepseek','opencode') and not adapter.get('isolated_environment'):
                raise ValueError('Run this adapter under a dedicated OS account/container and set isolated_environment=true; a temporary folder is not a sandbox')
        token_name=config.get('token_env','FILSAT_TOKEN')
        if not token_name.upper().startswith('FILSAT'):
            raise ValueError('The token environment variable must start with FILSAT')
        token=os.environ.get(token_name)
        if not token: raise ValueError('Set the Filsat runner token environment variable first')
        self.client=Client(config['site_url'],token)
        self.temp=(Path(config_dir)/'temporary').resolve()
        self.temp.mkdir(mode=0o777 if os.name=='nt' else 0o700,parents=True,exist_ok=True)
        self.parallel=max(1,min(int(config.get('concurrency',1)),4))
        self.shutdown=threading.Event()
        self.health=Readiness(self.temp)
        self.ready=[]

    def execute(self,job):
        if not re.fullmatch(r'[a-fA-F0-9-]{36}',job.get('id','')): raise ValueError('Invalid job ID')
        config=self.services[str(job['product_id'])]
        stop=threading.Event(); state={'stage':'sending_inputs'}; guard=threading.Lock()
        base=f"/orders/{job['id']}"; lease=job['lease']
        def progress(stage):
            with guard: state['stage']=stage
        def heartbeat():
            failures=0
            while not stop.is_set():
                if self.shutdown.is_set(): stop.set(); return
                try:
                    with guard: stage=state['stage']
                    self.client.call(base+'/heartbeat',{'stage':stage},lease)
                    failures=0
                except Exception:
                    failures+=1
                    if failures>=3: stop.set(); return
                stop.wait(15)
        thread=threading.Thread(target=heartbeat,daemon=True); thread.start()
        work=self.temp/('job-'+job['id']+'-'+uuid.uuid4().hex)
        work.mkdir(mode=0o777 if os.name=='nt' else 0o700)
        success=False
        try:
            (work/'inputs').mkdir(); (work/'outputs').mkdir()
            inputs=download_inputs(self.client,job,work)
            prompt=make_prompt(job,inputs)
            # Never write the lease, site token, provider key, or full job transport object to this folder.
            progress('thinking')
            fallback=adapters.run(config,prompt,work,progress,stop,min(int(job['timeout_seconds']),3600)-10)
            if stop.is_set(): raise RuntimeError('Seller connection lost')
            text,files=deliverables(work,fallback)
            if job.get('output_kind','text')!='text' and not files:
                raise ValueError('The service promised files but the provider did not produce them')
            progress('uploading')
            self.client.call(base+'/heartbeat',{'stage':'uploading'},lease)
            for path in files:
                self.retry(lambda:self.client.upload(job['id'],lease,path))
            self.retry(lambda:self.client.call(base+'/complete',{'output':text},lease))
            success=True
            print(f"Completed order {job['id']}",flush=True)
        except Exception as error:
            self.health.invalidate(config)
            # Only type is logged. Never echo a provider exception containing request data.
            print(f"Stopped order {job['id']} ({type(error).__name__}); check account status.",flush=True)
            try: self.client.call(base+'/fail',{},lease)
            except Exception: pass
        finally:
            stop.set(); thread.join(timeout=5)
            # This exact UUID child belongs to the runner. Never follow replacement links.
            if work.parent.resolve()==self.temp and not work.is_symlink():
                shutil.rmtree(work,ignore_errors=True)
                if work.exists(): print('Temporary job cleanup incomplete; remove retained customer data after closing its provider.',flush=True)
        return success

    @staticmethod
    def retry(action):
        for attempt in range(3):
            try: return action()
            except Exception:
                if attempt==2: raise
                time.sleep(2**attempt)

    def run(self,once=False):
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.parallel) as pool, concurrent.futures.ThreadPoolExecutor(max_workers=4) as probes:
            active=set()
            pending_checks={}
            try:
                while True:
                    active={f for f in active if not f.done()}
                    try:
                        services=self.client.call('/services')['services']
                        ready=[]
                        for service in services:
                            adapter=self.services.get(str(service['id']))
                            if not (adapter and service['published'] and service['review_status']=='approved' and service['in_hours']): continue
                            if once:
                                healthy=self.health.check(adapter)
                            else:
                                healthy=self.health.cached(adapter)
                                key=self.health.key(adapter)
                                if healthy is None and (key not in pending_checks or pending_checks[key].done()): pending_checks[key]=probes.submit(self.health.check,adapter)
                            if healthy: ready.append(service['id'])
                        self.client.call('/presence',{'ready_product_ids':ready})
                        if ready!=self.ready:
                            print('Ready service IDs: '+(', '.join(map(str,ready)) or 'none (offline or outside hours)'),flush=True)
                            self.ready=ready
                    except Exception as error:
                        self.ready=[]
                        print(f'Connection/readiness update unavailable ({type(error).__name__}).',flush=True)
                        if once: raise
                    if len(active)<self.parallel:
                        try:
                            if not self.ready:
                                if once: return False
                                time.sleep(30); continue
                            response=self.client.call('/claim',{'product_ids':self.ready})
                            if response.get('job'): active.add(pool.submit(self.execute,response['job']))
                        except Exception as error:
                            print(f'Polling unavailable ({type(error).__name__}); retrying in 30 seconds.',flush=True)
                            if once: raise
                    if once:
                        return all(f.result() for f in active)
                    time.sleep(30)
            except KeyboardInterrupt:
                self.shutdown.set()
                self.health.stop.set()
                raise
            finally:
                try: self.client.call('/presence',{'ready_product_ids':[]})
                except Exception: pass
