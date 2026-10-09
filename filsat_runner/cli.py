import argparse
import json
import shutil
import sys
from pathlib import Path
from .worker import Worker
from .adapters import executable

def main():
    parser=argparse.ArgumentParser(description='Run only your explicitly bound Filsat seller services.')
    parser.add_argument('command',choices=['run','doctor'])
    parser.add_argument('--config',default='runner.json')
    parser.add_argument('--once',action='store_true',help='Poll once and finish any claimed job')
    args=parser.parse_args()
    if args.command=='doctor':
        for name in ('codex','claude','opencode','pi','dsh'):
            print(name+': '+('found' if shutil.which(name) else 'not on PATH'))
        print('Sign in using each provider CLI yourself. Login files are never copied or uploaded.')
        print('n8n: requires a running published webhook. ClamAV scanning occurs at the Filsat server.')
        return
    try:
        path=Path(args.config).resolve()
        config=json.loads(path.read_text(encoding='utf-8-sig'))
        success=Worker(config,path.parent).run(args.once)
        if success is False: sys.exit(1)
    except KeyboardInterrupt:
        print('Runner stopped. Interrupted leases expire automatically.')
    except Exception as error:
        if isinstance(error,ValueError): print(str(error),file=sys.stderr)
        else: print(f'Runner stopped: {type(error).__name__}. Check configuration and service availability.',file=sys.stderr)
        sys.exit(1)

if __name__=='__main__': main()
