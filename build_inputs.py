"""Verify frozen source inputs without consulting the staging checkout."""
import hashlib,json
from pathlib import Path

def verify_source(root):
    source=root/'source'
    expected=json.loads((root/'source-inputs.json').read_text())['files']
    actual={str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    if actual!=expected:
        changed=sorted(k for k in actual.keys()|expected.keys() if actual.get(k)!=expected.get(k))
        raise ValueError('frozen_source_changed: '+', '.join(changed[:8]))
    mapping=json.loads((root/'overlay-inputs.json').read_text())
    for name,target in mapping.items():
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('invalid_source_mapping')
        path=(root/target).resolve()
        if not path.is_relative_to((root/'src').resolve()) or not path.is_file():
            raise ValueError('external_overlay_input')
    return len(actual)
