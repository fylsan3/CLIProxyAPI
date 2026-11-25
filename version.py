"""Reject a mixed central/worker/broker candidate before startup."""
import functools,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
VERSION='container-native5'
@functools.lru_cache(maxsize=1)
def release_info():
 manifest=json.loads((ROOT/'release-manifest.json').read_text())
 for name,want in manifest['files'].items():
  path=ROOT/name
  if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=want:raise ValueError('candidate_file_mismatch: '+name)
 image=json.loads((ROOT/'image.json').read_text())
 if any(image[k]!=v for k,v in manifest['images'].items()):raise ValueError('candidate_image_mismatch')
 return {'candidate':VERSION,'real_provider_verified':False,'published':False,'protocol':'claude/openai/responses/gemini','image':image['id'],'worker_sha256':image['worker_sha256'],'central_sha256':manifest['files']['central/cli-proxy-api']}
