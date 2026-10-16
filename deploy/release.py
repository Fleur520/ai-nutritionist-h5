"""Immutable application releases with acceptance checks and automatic rollback."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.request


class ReleaseManager:
    def __init__(self, root, project='ai-nutritionist-h5', base_url='http://172.16.10.3:18080', startup_timeout=90, model_check=True):
        self.root=Path(root).resolve();self.project=project;self.base_url=base_url.rstrip('/')
        self.startup_timeout=startup_timeout;self.model_check=model_check
        self.state_dir=self.root/'.delivery';self.state_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
        (self.state_dir/'reports').mkdir(exist_ok=True)
        self.compose=['docker','compose']
        if subprocess.run(self.compose+['version'],capture_output=True).returncode:
            self.compose=['docker-compose']

    def write_json(self,path,data):
        path=Path(path);temp=path.with_suffix(path.suffix+'.tmp')
        temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temp.chmod(0o600)
        temp.replace(path)

    def current(self):
        path=self.state_dir/'active.json'
        return json.loads(path.read_text()) if path.exists() else None

    @contextmanager
    def locked(self):
        import fcntl
        with (self.state_dir/'deploy.lock').open('a') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX)
            yield

    def run(self,command,*,input=None,timeout=600):
        result=subprocess.run(command,input=input,text=True,capture_output=True,timeout=timeout,
            env={**os.environ,'DOCKER_BUILDKIT':'0','COMPOSE_DOCKER_CLI_BUILD':'0'})
        with (self.state_dir/'deployment.log').open('a',encoding='utf-8') as log:
            log.write(result.stdout or '');log.write(result.stderr or '')
        if result.returncode:
            raise RuntimeError('Command failed: '+' '.join(command[:5]))
        return result.stdout.strip()

    def command(self,release,*args):
        return self.compose+['-p',self.project,'--env-file',str(self.root/'.env'),
            '-f',str(Path(release['directory'])/'docker-compose.yml'),
            '-f',str(Path(release['directory'])/'release.override.json'),*args]

    def override(self,release):
        self.write_json(Path(release['directory'])/'release.override.json',{'services':{
            'api':{'image':release['api_image'],'environment':{'APP_REVISION':release['revision']}},
            'web':{'image':release['web_image']}}})

    def adopt(self):
        revision='adopt-'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
        folder=self.state_dir/'releases'/revision;folder.mkdir(parents=True)
        shutil.copy2(self.root/'docker-compose.yml',folder/'docker-compose.yml')
        (folder/'.env').symlink_to(self.root/'.env')
        for name in ('backend','frontend'):
            (folder/name).symlink_to(self.root/name,target_is_directory=True)
        release={'revision':revision,'directory':str(folder),'legacy':True}
        for service in ('api','web'):
            ids=self.run(['docker','ps','-q','--filter','label=com.docker.compose.project='+self.project,
                '--filter','label=com.docker.compose.service='+service]).splitlines()
            if len(ids)!=1:raise RuntimeError('Expected one running '+service+' container')
            image=self.run(['docker','inspect','--format','{{.Image}}',ids[0]])
            tag='local/'+self.project+'-'+service+':'+revision
            self.run(['docker','image','tag',image,tag]);release[service+'_image']=tag
        self.override(release);self.write_json(self.state_dir/'active.json',release)
        return release

    def prepare(self,source,revision):
        target=self.state_dir/'releases'/revision/'source'
        if not target.exists():
            def ignore(directory,names):
                blocked={'.git','data','.delivery','node_modules','dist','__pycache__','.pytest_cache'}
                return [x for x in names if x in blocked or (x.startswith('.env') and x!='.env.example') or x.endswith('.tgz')]
            shutil.copytree(source,target,ignore=ignore)
        env=target/'.env'
        if not env.exists():env.symlink_to(self.root/'.env')
        release={'revision':revision,'directory':str(target),'legacy':False,
            'api_image':'local/'+self.project+'-api:'+revision,
            'web_image':'local/'+self.project+'-web:'+revision}
        self.override(release);return release

    def health(self):
        deadline=time.monotonic()+self.startup_timeout
        while time.monotonic()<deadline:
            try:
                with urllib.request.urlopen(self.base_url+'/api/health',timeout=3) as response:
                    if json.load(response).get('status')=='ok':return
            except Exception:pass
            time.sleep(1)
        raise RuntimeError('Application did not become healthy')

    def verify(self,release):
        self.health()
        if release.get('legacy'):return
        script=Path(release['directory'])/'deploy'/'smoke.py'
        args=['exec','-T','api','python','-','--revision',release['revision']]
        if self.model_check:args.append('--model-check')
        result=self.run(self.command(release,*args),input=script.read_text(encoding='utf-8'),timeout=140)
        report=json.loads(result)
        if report.get('status')!='passed':raise RuntimeError('Acceptance did not pass')
        return report

    def deploy(self,source,revision):
        if not re.fullmatch(r'[0-9a-f]{40}',revision):raise ValueError('Expected a full commit SHA')
        if not (self.root/'.env').is_file():raise RuntimeError('Server .env is missing')
        with self.locked():
            previous=self.current() or self.adopt()
            if previous['revision']==revision:return {'status':'already-deployed','revision':revision}
            release=self.prepare(Path(source),revision);switched=False;stage='build'
            report={'revision':revision,'previous_revision':previous['revision']}
            try:
                self.run(self.command(release,'config','--quiet'))
                self.run(self.command(release,'build'))
                stage='database-bootstrap'
                self.run(self.command(release,'run','--rm','--no-deps','api','python','-m','app.bootstrap_db'))
                stage='start';switched=True
                self.run(self.command(release,'up','-d','--no-build','api','web'))
                stage='acceptance';report['acceptance']=self.verify(release)
                self.write_json(self.state_dir/'previous.json',previous)
                self.write_json(self.state_dir/'active.json',release)
                report['status']='deployed'
            except Exception as exc:
                report.update(status='build-failed' if not switched else 'rolling-back',failed_stage=stage,error=type(exc).__name__)
                if switched:
                    try:
                        self.run(self.command(previous,'up','-d','--no-build','api','web'))
                        self.verify(previous);report['status']='rolled-back'
                    except Exception:
                        report['status']='rollback-failed'
                self.write_json(self.state_dir/'reports'/(revision+'.json'),report)
                raise RuntimeError(json.dumps(report,ensure_ascii=False)) from exc
            self.write_json(self.state_dir/'reports'/(revision+'.json'),report)
            return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True)
    parser.add_argument('--source',required=True);parser.add_argument('--revision',required=True)
    parser.add_argument('--project',default='ai-nutritionist-h5')
    parser.add_argument('--base-url',default='http://172.16.10.3:18080')
    parser.add_argument('--startup-timeout',type=int,default=90);parser.add_argument('--skip-model-check',action='store_true')
    args=parser.parse_args()
    manager=ReleaseManager(args.root,args.project,args.base_url,args.startup_timeout,not args.skip_model_check)
    print(json.dumps(manager.deploy(args.source,args.revision),ensure_ascii=False),flush=True)
