"""Build on disposable GitHub Ubuntu only; never publishes to a registry."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile

from ci_vm_common import (ARCHIVES, DEMO, REPORT, ROOT, attest, docker, require,
                          sha256, write_json)


def oci_identity(path):
    with tarfile.open(path) as archive:
        index = json.load(archive.extractfile('index.json'))
        descriptor, = index['manifests']
        while True:
            algorithm, digest = descriptor['digest'].split(':')
            require(algorithm == 'sha256', 'VM_CI_OCI_ALGORITHM')
            content = archive.extractfile('blobs/sha256/' + digest).read()
            require(hashlib.sha256(content).hexdigest() == digest, 'VM_CI_OCI_BLOB_MISMATCH')
            manifest = json.loads(content)
            if 'config' in manifest:
                break
            descriptor, = manifest['manifests']
        config_digest = manifest['config']['digest']
        config = archive.extractfile('blobs/sha256/' + config_digest.split(':')[1]).read()
        require('sha256:' + hashlib.sha256(config).hexdigest() == config_digest, 'VM_CI_CONFIG_DIGEST')
        return descriptor['digest'], config_digest


def main():
    _, revision = attest()  # Must precede even buildx/pull/image inspection.
    builder = os.environ.get('CI_VM_BUILDER', '')
    require(re.fullmatch('[a-zA-Z0-9_.-]+', builder) is not None, 'VM_CI_BUILDER_REQUIRED')
    lock = json.loads((DEMO / 'images.lock.json').read_text())
    for filename, digest in lock['dependency_sha256'].items():
        require(sha256(ROOT / filename) == digest, 'VM_CI_DEPENDENCY_LOCK_CHANGED')
    lock.update(build_status='BUILT', vm_compatibility='NOT_TESTED', build_revision=revision,
                run_url='https://github.com/tangwencan666/AgentForge-AI/actions/runs/' + os.environ['GITHUB_RUN_ID'])
    with tempfile.TemporaryDirectory(prefix='vm-mock-build-', dir=os.environ['RUNNER_TEMP']) as temporary:
        temporary = Path(temporary)
        for name, roles in [('backend', ['api', 'worker']), ('frontend', ['frontend'])]:
            tag = 'local/agentforge-vm-mock-' + name + ':' + revision
            oci_path, docker_path = temporary / (name + '.oci.tar'), temporary / (name + '.docker.tar')
            metadata = REPORT / (name + '-build-metadata.json')
            docker('buildx', 'build', '--builder', builder, '--platform', 'linux/amd64',
                   '--provenance=false', '--sbom=false', '--build-arg', 'BUILD_REVISION=' + revision,
                   '--tag', tag, '--file', str(DEMO / ('Dockerfile.' + name)),
                   '--output', 'type=oci,dest=' + str(oci_path),
                   '--output', 'type=docker,dest=' + str(docker_path),
                   '--metadata-file', str(metadata), str(ROOT), timeout=1200, capture=False)
            oci_digest, config_digest = oci_identity(oci_path)
            docker('image', 'load', '--input', str(docker_path), timeout=180, capture=False)
            row, = json.loads(docker('image', 'inspect', tag))
            require(row['Id'] == config_digest and row['Architecture'] == 'amd64'
                    and row['Os'] == 'linux', 'VM_CI_LOADED_IMAGE_MISMATCH')
            require(row['Config']['Labels']['org.opencontainers.image.revision'] == revision,
                    'VM_CI_IMAGE_REVISION_MISMATCH')
            lock['artifacts'][name].update(logical_names=roles, repository_tag=tag,
                reference=config_digest, image_id=row['Id'], config_digest=config_digest,
                oci_manifest_digest=oci_digest, repo_digests=row.get('RepoDigests') or [],
                registry_published=False, architecture=row['Architecture'], os=row['Os'],
                size_bytes=row['Size'], base_image=lock['bases']['backend' if name == 'backend' else 'frontend_runtime'],
                build_revision=revision)
            oci_path.unlink()
            docker_path.unlink()
        lock['official_dependencies'] = {}
        for name in ('postgres', 'redis'):
            reference = lock['bases'][name]
            docker('image', 'pull', '--platform', 'linux/amd64', reference, timeout=180, capture=False)
            row, = json.loads(docker('image', 'inspect', reference))
            require(row['Architecture'] == 'amd64' and row['Os'] == 'linux', 'VM_CI_DEPENDENCY_PLATFORM')
            archive_tag = 'local/agentforge-vm-mock-' + name + ':' + revision
            docker('image', 'tag', row['Id'], archive_tag)
            lock['official_dependencies'][name] = {'reference': reference, 'image_id': row['Id'],
                'archive_tag': archive_tag,
                'repo_digests': row.get('RepoDigests') or [], 'size_bytes': row['Size'],
                'architecture': row['Architecture'], 'os': row['Os']}
        ARCHIVES.mkdir(parents=True, exist_ok=True)
        # Explicit allowlist: two new application images and the two approved
        # official dependencies. Never commit a container filesystem or volume.
        references = [lock['artifacts'][n]['repository_tag'] for n in ('backend', 'frontend')]
        references += [lock['official_dependencies'][n]['archive_tag'] for n in ('postgres', 'redis')]
        saved = temporary / 'images.tar'
        docker('image', 'save', '--output', str(saved), *references, timeout=300)
        with tarfile.open(saved) as archive:
            manifest = json.load(archive.extractfile('manifest.json'))
            tags = {tag for row in manifest for tag in row.get('RepoTags') or []}
            require(tags == set(references) and len(manifest) == 4, 'VM_CI_ARCHIVE_ALLOWLIST')
            saved_ids = {'sha256:' + hashlib.sha256(archive.extractfile(row['Config']).read()).hexdigest()
                         for row in manifest}
            expected_ids = {lock['artifacts'][name]['image_id'] for name in ('backend', 'frontend')}
            expected_ids.update(lock['official_dependencies'][name]['image_id'] for name in ('postgres', 'redis'))
            require(saved_ids == expected_ids, 'VM_CI_ARCHIVE_CONFIG_MISMATCH')
        target = ARCHIVES / 'agentforge-vm-mock-amd64.tar.gz'
        with saved.open('rb') as source, target.open('wb') as raw:
            with gzip.GzipFile(filename='', mode='wb', fileobj=raw, compresslevel=1, mtime=0) as compressed:
                shutil.copyfileobj(source, compressed)
        lock['archive'] = {'file': target.name, 'sha256': sha256(target),
                           'size_bytes': target.stat().st_size, 'images': references,
                           'image_ids': sorted(expected_ids),
                           'retention_days': 3, 'format': 'docker-save+gzip'}
    write_json('images.resolved.json', lock)
    (ARCHIVES / 'SHA256SUMS').write_text(lock['archive']['sha256'] + '  ' + target.name + '\n')
    print(json.dumps(lock, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Hosted image build failed: ' + (str(error) if type(error) is RuntimeError else type(error).__name__))
        raise SystemExit(1) from None
