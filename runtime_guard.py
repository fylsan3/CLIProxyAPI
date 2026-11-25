"""Shared admission checks for offline container brokers; never accepts caller commands."""
class PolicyError(ValueError):
    pass


class Bindings:
    """Pin a browser container after its first successful configuration check."""
    def __init__(self, path):
        import json
        import threading
        from storage_guard import private_directory, private_file
        private_directory(path.parent)
        private_file(path)
        self.path, self.lock = path, threading.Lock()
        self.rows = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(self.rows, dict):
            raise PolicyError('container_binding_mismatch')

    def verify(self, owner, ident):
        import json
        import os
        import tempfile
        with self.lock:
            previous = self.rows.get(owner)
            if previous is not None:
                if previous != ident: raise PolicyError('container_binding_mismatch')
                return
            updated = dict(self.rows, **{owner: ident})
            fd, name = tempfile.mkstemp(dir=self.path.parent, prefix='.binding-')
            try:
                with os.fdopen(fd, 'w') as out:
                    json.dump(updated, out); out.flush(); os.fsync(out.fileno())
                os.replace(name, self.path)
                directory = os.open(self.path.parent, os.O_RDONLY)
                try: os.fsync(directory)
                finally: os.close(directory)
            finally:
                if os.path.exists(name): os.unlink(name)
            self.rows = updated


def check_container(info, *, image, labels, volume, destination, writable, pinned=None):
    if not isinstance(info, dict):
        raise PolicyError('project_container_missing')
    config = info.get('Config') or {}
    host = info.get('HostConfig') or {}
    ident = info.get('Id', '')
    if (info.get('Image') != image or (pinned and not (ident == pinned or ident[:12] == pinned))
            or any((config.get('Labels') or {}).get(k) != v for k,v in labels.items())
            or host.get('NetworkMode') != 'none' or host.get('Privileged') is not False
            or host.get('ReadonlyRootfs') is not True or host.get('PortBindings')
            or set((info.get('NetworkSettings') or {}).get('Networks') or {}) - {'none'}
            or host.get('PidMode') or host.get('IpcMode') not in ('', 'private', None)
            or host.get('Devices') or host.get('DeviceRequests') or host.get('CapAdd')
            or 'ALL' not in (host.get('CapDrop') or [])
            or not any(x in ('no-new-privileges', 'no-new-privileges:true') for x in host.get('SecurityOpt') or [])):
        raise PolicyError('container_binding_mismatch')
    mounts = [m for m in info.get('Mounts', []) if m.get('Type') != 'tmpfs']
    if (len(mounts) != 1 or mounts[0].get('Type') != 'volume'
            or mounts[0].get('Name') != volume or mounts[0].get('Destination') != destination
            or mounts[0].get('RW') is not writable):
        raise PolicyError('volume_binding_mismatch')
    # Only the configured scratch directory may be overlaid with tmpfs.
    if (set(host.get('Tmpfs') or {}) - {'/tmp'}
            or any(m.get('Type') == 'tmpfs' and m.get('Destination') != '/tmp' for m in info.get('Mounts', []))):
        raise PolicyError('volume_binding_mismatch')
    return ident


def check_volume(info, name, labels=None):
    if (not isinstance(info, dict) or info.get('Name') != name
            or info.get('Driver') != 'local' or info.get('Scope') != 'local' or info.get('Options')
            or any((info.get('Labels') or {}).get(k) != v for k,v in (labels or {}).items())):
        raise PolicyError('volume_binding_mismatch')


def body_object(headers, stream, *, empty_only=False):
    """Reject ambiguous framing and unsupported management parameters before dispatch."""
    import json
    lengths = headers.get_all('Content-Length', [])
    if headers.get('Transfer-Encoding') or len(lengths) != 1:
        raise PolicyError('invalid_request')
    try:
        size = int(lengths[0])
    except ValueError:
        raise PolicyError('invalid_request') from None
    if not 0 <= size <= 65536:
        raise PolicyError('invalid_request')
    raw = stream.read(size)
    if len(raw) != size:
        raise PolicyError('invalid_request')
    try:
        value = json.loads(raw or b'{}')
    except ValueError:
        raise PolicyError('invalid_request') from None
    if not isinstance(value, dict) or (empty_only and value):
        raise PolicyError('invalid_request')
    return raw, value
