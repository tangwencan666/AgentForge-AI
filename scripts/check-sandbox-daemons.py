"""Only local, configured named-pipe Engine identity GETs. Never starts a Runner."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.sandbox.daemon_isolation import DaemonObservation, independent_candidates


def inspect_local():
    env={n:os.environ[n] for n in ('SystemRoot','WINDIR','PATH','PATHEXT','COMSPEC','TEMP','TMP',
        'APPDATA','LOCALAPPDATA','USERPROFILE','HOMEDRIVE','HOMEPATH') if n in os.environ}
    def read(args):
        r=subprocess.run(['docker',*args],env=env,capture_output=True,text=True,encoding='utf-8',timeout=8)
        return r.stdout if r.returncode==0 else None
    listing=read(['context','ls','--format','{{json .}}'])
    if listing is None: return {'status':'BLOCKED','reason':'DOCKER_CONTEXT_UNVERIFIED','external_model_requests':0}
    rows=[]; main=None; untested=0
    for text in listing.splitlines():
        row=json.loads(text); endpoint=row.get('DockerEndpoint');name=row['Name']
        if endpoint not in {'npipe:////./pipe/docker_engine','npipe:////./pipe/dockerDesktopLinuxEngine'}:
            untested+=1
            continue  # No unapproved remote probing or TLS credential reads.
        data=read(['--context',name,'info','--format','{"id":{{json .ID}},"os":{{json .OSType}}}'])
        identity=json.loads(data) if data else {}
        observation=DaemonObservation(name,endpoint,identity.get('id'),identity.get('os'))
        rows.append(observation)
        if row.get('Current'):main=observation
    result=independent_candidates(main,rows)
    result.update(observations=[{'context':r.context,'endpoint':r.endpoint,'daemon_id':r.daemon_id,
        'operating_system':r.operating_system} for r in rows],other_contexts_not_probed=untested,external_model_requests=0)
    return result


if __name__=='__main__':
    try: print(json.dumps(inspect_local()))
    except Exception:
        print(json.dumps({'status':'BLOCKED','reason':'DAEMON_OBSERVATION_UNVERIFIED','external_model_requests':0}))
        raise SystemExit(2) from None
