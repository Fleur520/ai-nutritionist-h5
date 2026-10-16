"""Pull only main commits whose GitHub Actions CI completed successfully."""
import argparse
from datetime import datetime, timezone
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import time
import urllib.error
import urllib.request

from release import ReleaseManager


def fetch(url, *, binary=False):
    request=urllib.request.Request(url,headers={'Accept':'application/vnd.github+json','User-Agent':'nutrition-delivery'})
    with urllib.request.urlopen(request,timeout=30) as response:
        data=response.read(30*1024*1024+1)
    if len(data)>30*1024*1024:raise RuntimeError('GitHub response exceeds size limit')
    return data if binary else json.loads(data)


def extract_source(content,target):
    target=Path(target).resolve();target.mkdir(parents=True,exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(content),mode='r:gz') as archive:
        members=archive.getmembers()
        if len(members)>10000 or sum(x.size for x in members)>150*1024*1024:
            raise ValueError('Archive exceeds limits')
        for member in members:
            path=PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or not (member.isdir() or member.isfile()):
                raise ValueError('Unsafe archive entry')
            relative=Path(*path.parts[1:])
            if not relative.parts:continue
            destination=(target/relative).resolve()
            if not destination.is_relative_to(target):raise ValueError('Archive path escapes target')
            if member.isdir():
                destination.mkdir(parents=True,exist_ok=True)
                destination.chmod(0o755)
            else:
                destination.parent.mkdir(parents=True,exist_ok=True)
                # systemd uses UMask=0077. Public source must still be readable
                # by the non-root runtime user after Docker COPY.
                parent=destination.parent
                while parent.is_relative_to(target):
                    parent.chmod(0o755)
                    if parent==target:break
                    parent=parent.parent
                with archive.extractfile(member) as source,destination.open('wb') as output:
                    output.write(source.read())
                destination.chmod(0o755 if member.mode & 0o111 else 0o644)


def check(config):
    repo=config['repository'];branch=config.get('branch','main');workflow=config.get('workflow','ci.yml')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo) or branch!='main' or not re.fullmatch(r'[A-Za-z0-9_.-]+\.yml',workflow):
        raise ValueError('Only the configured main branch and named CI workflow are allowed')
    manager=ReleaseManager(config['root'],config.get('project','ai-nutritionist-h5'),config['base_url'],
        config.get('startup_timeout',90),config.get('model_check',True))
    api='https://api.github.com/repos/'+repo
    commit=fetch(api+'/commits/'+branch);sha=commit['sha']
    if not re.fullmatch(r'[0-9a-f]{40}',sha):raise ValueError('Invalid commit SHA')
    current=manager.current()
    if current and current['revision']==sha:return {'status':'up-to-date','revision':sha}
    report=manager.state_dir/'reports'/(sha+'.json')
    if report.exists() and json.loads(report.read_text()).get('status') in {'rolled-back','rollback-failed','build-failed'}:
        return {'status':'failed-revision-held','revision':sha}
    try:
        runs=fetch(api+'/actions/workflows/'+workflow+'/runs?branch=main&event=push&head_sha='+sha+'&per_page=5')['workflow_runs']
    except urllib.error.HTTPError as exc:
        if exc.code==404:return {'status':'waiting-for-ci-workflow','revision':sha}
        raise
    successful=[run for run in runs if run.get('head_sha')==sha and run.get('event')=='push'
        and run.get('head_branch')=='main' and run.get('status')=='completed' and run.get('conclusion')=='success']
    if not successful:return {'status':'waiting-for-successful-ci','revision':sha}
    source=manager.state_dir/'downloads'/sha
    if not (source/'docker-compose.yml').exists():
        extract_source(fetch(api+'/tarball/'+sha,binary=True),source)
    result=manager.deploy(source,sha);result['ci_run_url']=successful[0]['html_url']
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--once',action='store_true')
    args=parser.parse_args();config=json.loads(Path(args.config).read_text(encoding='utf-8'))
    interval=max(180,int(config.get('interval_seconds',300)))
    while True:
        try:result=check(config)
        except Exception as exc:result={'status':'controller-error','error':type(exc).__name__,'message':str(exc)[:300]}
        result['checked_at']=datetime.now(timezone.utc).isoformat()
        path=Path(config['root'])/'.delivery'/'controller-status.json';path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_suffix('.tmp');temp.write_text(json.dumps(result,ensure_ascii=False,indent=2));temp.replace(path)
        print(json.dumps(result,ensure_ascii=False),flush=True)
        if args.once:
            raise SystemExit(1 if result['status']=='controller-error' else 0)
        time.sleep(interval)
