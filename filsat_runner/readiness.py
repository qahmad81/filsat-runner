import json
import os
import threading
import time
import uuid
import shutil
from urllib.parse import urlparse,urlunparse
from . import adapters
from .http import request

class Readiness:
    def __init__(self,root): self.root=root; self.cache={}; self.stop=threading.Event()
    def key(self,config): return json.dumps(config,sort_keys=True)
    def invalidate(self,config): self.cache.pop(self.key(config),None)
    def cached(self,config):
        value=self.cache.get(self.key(config))
        return value[1] if value and time.monotonic()<value[0] else None
    def check(self,config):
        key=self.key(config); previous=self.cache.get(key)
        if previous and time.monotonic()<previous[0]: return previous[1]
        work=self.root/('probe-'+uuid.uuid4().hex)
        work.mkdir(mode=0o777 if os.name=='nt' else 0o700)
        (work/'inputs').mkdir();(work/'outputs').mkdir()
        ready=False
        try:
            if config['kind']=='n8n':
                url=urlparse(config['url'])
                health=config.get('health_url',urlunparse((url.scheme,url.netloc,'/healthz','','','')))
                result=request(health,timeout=8)
                ready=result.get('status')=='ok' and config.get('workflow_ready') is True
            else:
                # One inexpensive actual provider response on startup and after failures verifies login/model readiness.
                # Cached for ten minutes per distinct adapter, not repeated per service or every poll.
                probe=dict(config)
                if probe['kind']=='openrouter': probe['max_tokens']=32
                reply=adapters.run(probe,'Reply exactly FILSAT_READY. Do not use any tools, read files, write files or perform any other action.',work,lambda _:None,self.stop,90)
                ready=isinstance(reply,str) and reply.strip().strip('`')=='FILSAT_READY'
        except Exception: ready=False
        finally:
            if work.parent.resolve()==self.root.resolve() and not work.is_symlink(): shutil.rmtree(work,ignore_errors=True)
        self.cache[key]=(time.monotonic()+(600 if ready else 60),ready)
        return ready
