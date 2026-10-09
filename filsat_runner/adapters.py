"""Local configuration selects executables. Job data is never a shell command."""
import base64
import json
import mimetypes
import os
import queue
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
from .http import request
from .files import MAX_FILE, MAX_TOTAL
from .processes import ProcessTree

KINDS = {'codex','claude','opencode','pi','deepseek','openrouter','n8n'}

def executable(command):
    command = list(command)
    found = shutil.which(command[0]) or command[0]
    if os.name == 'nt' and str(found).lower().endswith(('.cmd','.ps1')):
        # Resolve standard npm shims to node + script without invoking cmd.exe or interpolating prompts.
        text = Path(found).read_text(encoding='utf-8')
        match = re.search(r'"%_prog%"\s+"%dp0%[\\/]([^"\r\n]+)"', text, re.I)
        if not match:
            raise ValueError('Configure an explicit executable command, for example ["node", "C:/path/cli.js"]')
        target = (Path(found).parent / match[1].replace('\\','/')).resolve()
        if not target.is_relative_to(Path(found).parent.resolve()):
            raise ValueError('Unexpected npm shim target')
        return [shutil.which('node') or 'node', str(target), *command[1:]]
    return [str(found), *command[1:]]

def command_for(config, workspace):
    kind = config['kind']
    default = {'codex':['codex'],'claude':['claude'],'opencode':['opencode'],'pi':['pi'],'deepseek':['dsh']}
    command = executable(config.get('command', default.get(kind, [])))
    model = config.get('model')
    if kind == 'codex':
        command += ['exec','--ignore-user-config','--skip-git-repo-check','--ephemeral','--sandbox','workspace-write','--json','--output-last-message',str(workspace/'final.txt')]
        if os.name == 'nt': command += ['-c','windows.sandbox="unelevated"']
        if model: command += ['--model',model]
        command += ['-']
    elif kind == 'claude':
        command += ['-p','--output-format','stream-json','--verbose','--permission-mode','acceptEdits','--allowedTools','Read,Write,Edit,Glob,Grep']
        if model: command += ['--model',model]
    elif kind == 'opencode':
        command += ['run','--pure','--format','json']
        if model: command += ['--model',model]
    elif kind == 'pi':
        command += ['--print','--mode','json','--no-session','--no-extensions','--no-skills','--no-prompt-templates','--no-themes']
        if model: command += ['--model',model]
    elif kind == 'deepseek':
        command += ['--profile',config.get('profile','headless'),'--json']
    return command + config.get('args', [])

def environment(config):
    allowed = {'PATH','PATHEXT','SYSTEMROOT','WINDIR','COMSPEC','TEMP','TMP','HOME','USERPROFILE','APPDATA','LOCALAPPDATA','PROGRAMFILES','LANG','LC_ALL','TERM','CODEX_HOME','PI_CODING_AGENT_DIR','DSH_HOME'}
    allowed.update(config.get('env_names', []))
    env = {k:v for k,v in os.environ.items() if k.upper() in allowed and not k.upper().startswith('FILSAT')}
    env.update({'PYTHONIOENCODING':'utf-8','PI_OFFLINE':'1','NO_COLOR':'1'})
    # Config is seller owned. Provider keys may be allowlisted, but never the site runner token.
    env.update({k:str(v) for k,v in config.get('env',{}).items() if not k.upper().startswith('FILSAT')})
    return env

def event_stage(event):
    item = event.get('item') or event.get('part') or {}
    typ = item.get('type', '')
    tool = item.get('tool', '') or item.get('toolName','') or event.get('tool','')
    if typ == 'web_search' or tool in ('websearch','webfetch','WebSearch','WebFetch'):
        return 'searching'
    if typ == 'file_change' or tool in ('write','edit','Write','Edit','apply_patch'):
        return 'creating_tools'
    if event.get('type') in ('turn.started','message_start') or typ == 'reasoning':
        return 'thinking'
    return None

def cli(config, prompt, workspace, progress, stop, timeout):
    command = command_for(config,workspace)
    stdin_prompt = prompt
    tree=ProcessTree()
    try:
        proc = tree.spawn(command,cwd=workspace,env=environment(config),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace')
    except Exception:
        tree.close(); raise
    events = queue.Queue(maxsize=1024)
    reader_done = threading.Event()
    def read_stdout():
        try:
            for line in proc.stdout:
                if len(line)<1024*1024:
                    try: events.put(line,timeout=1)
                    except queue.Full: pass
        finally: reader_done.set()
    def drain_stderr():
        # Provider diagnostics can contain private prompts and keys. Do not publish or retain them.
        for _ in proc.stderr: pass
    threading.Thread(target=read_stdout,daemon=True).start()
    threading.Thread(target=drain_stderr,daemon=True).start()
    def feed():
        try: proc.stdin.write(stdin_prompt); proc.stdin.close()
        except (BrokenPipeError,OSError): pass
    threading.Thread(target=feed,daemon=True).start()
    began=time.monotonic(); final=[]; last_progress=None; output_size=0
    try:
        while proc.poll() is None or not reader_done.is_set() or not events.empty():
            if stop.is_set() or time.monotonic()-began>timeout:
                raise RuntimeError('Execution stopped or timed out')
            try: line=events.get(timeout=.2)
            except queue.Empty: line=None
            if line:
                output_size+=len(line)
                if output_size>8*1024*1024: raise RuntimeError('Provider output limit exceeded')
                try:
                    event=json.loads(line)
                    if event.get('type') in ('error','turn.failed'): raise RuntimeError('Provider reported an execution error')
                    stage=event_stage(event)
                    if stage: progress(stage)
                    if event.get('type')=='result':
                        if event.get('is_error'): raise RuntimeError('Provider reported failure')
                        final=[event.get('result','')]
                    if event.get('type')=='final': final=[event.get('text','')]
                    item=event.get('item',{})
                    if item.get('type')=='agent_message' and event.get('type')=='item.completed': final=[item.get('text','')]
                    if event.get('type')=='text' and event.get('part',{}).get('text'): final.append(event['part']['text'])
                    if event.get('type')=='message_end':
                        msg=event.get('message',{})
                        if msg.get('role')=='assistant': final=[''.join(p.get('text','') for p in msg.get('content',[]) if p.get('type')=='text')]
                except json.JSONDecodeError: pass
            progress_file=workspace/'progress.json'
            if progress_file.is_file() and not progress_file.is_symlink() and progress_file.stat().st_size<1024:
                try:
                    stage=json.loads(progress_file.read_text(encoding='utf-8')).get('stage')
                    if stage in ('searching','creating_tools','generating') and stage!=last_progress:
                        progress(stage); last_progress=stage
                except (ValueError,OSError): pass
        if proc.returncode!=0: raise RuntimeError(f"{config['kind']} exited unsuccessfully")
        return ''.join(final).strip()
    finally:
        tree.close(proc)

def run(config,prompt,workspace,progress,stop,timeout):
    kind=config['kind']
    if kind not in KINDS: raise ValueError('Unknown adapter')
    if kind not in ('n8n','openrouter'): return cli(config,prompt,workspace,progress,stop,timeout)
    progress('thinking')
    if kind=='n8n':
        url=urlparse(config['url'])
        if url.scheme!='https' and not (url.scheme=='http' and url.hostname in ('localhost','127.0.0.1','::1')):
            raise ValueError('n8n requires HTTPS except on loopback')
        payload={'prompt':prompt,'files':[]}
        for path in (workspace/'inputs').iterdir():
            payload['files'].append({'name':path.name,'base64':base64.b64encode(path.read_bytes()).decode()})
        headers={}
        if config.get('token_env'): headers[config.get('token_header','Authorization')]=os.environ[config['token_env']]
        result=request(config['url'],payload,headers,timeout=timeout)
        if isinstance(result,list) and len(result)==1: result=result[0]
        if not isinstance(result,dict) or not isinstance(result.get('text'),str): raise ValueError('n8n must return the documented result object, not an immediate acknowledgement')
        manifest={'text':result['text'],'files':[]}; total=0
        for i,file in enumerate(result.get('files',[])):
            if i>=5: raise ValueError('Too many n8n outputs')
            suffix=Path(file['name']).suffix.lower()
            body=base64.b64decode(file['base64'],validate=True); total+=len(body)
            if len(body)>MAX_FILE or total>MAX_TOTAL: raise ValueError('n8n output limit exceeded')
            name=f'result-{i+1}{suffix}'
            (workspace/'outputs'/name).write_bytes(body); manifest['files'].append(name)
        (workspace/'result.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
        return result['text']
    key=os.environ.get(config.get('key_env','OPENROUTER_API_KEY'))
    if not key: raise ValueError('OpenRouter key environment variable is missing')
    content=[{'type':'text','text':prompt+'\nYou have no filesystem tools. Return the requested result as text. The runner will deliver your response directly.'}]
    for path in (workspace/'inputs').iterdir():
        if path.suffix in ('.png','.jpg','.jpeg','.webp','.gif'):
            content.append({'type':'image_url','image_url':{'url':'data:'+mimetypes.guess_type(path.name)[0]+';base64,'+base64.b64encode(path.read_bytes()).decode()}})
        elif path.suffix in ('.txt','.md','.csv','.json'):
            if path.stat().st_size>100000: raise ValueError('OpenRouter text attachments must be under 100 KB')
            content.append({'type':'text','text':path.name+'\n'+path.read_text(encoding='utf-8')})
        else: raise ValueError('Use a CLI or n8n adapter for binary document processing')
    result=request('https://openrouter.ai/api/v1/chat/completions',{'model':config['model'],'messages':[{'role':'user','content':content}],'max_tokens':config.get('max_tokens',4096)}, {'Authorization':'Bearer '+key},timeout=timeout)
    return result['choices'][0]['message']['content']
