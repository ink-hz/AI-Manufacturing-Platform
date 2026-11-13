"""Private, bounded, atomic evidence cache. Never stores wire payloads or secrets."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile

from .errors import SapAccessError

MAX_BYTES = 5 * 1024 * 1024
EVENT_FIELDS = {'request_id', 'operation', 'function', 'timestamp', 'elapsed_ms',
                'status', 'error_code', 'response_bytes', 'contract_digest', 'actor_hash', 'binding', 'row_count', 'source_request_id'}


class SapAuditStore:
    def __init__(self, path):
        self.path = path

    def _check(self):
        if not isinstance(self.path, str) or not os.path.isabs(self.path):
            raise SapAccessError('SAP_AUDIT_UNAVAILABLE')

    @contextmanager
    def _lock(self):
        self._check()
        fd = None
        try:
            fd = os.open(self.path+'.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            self._check_file(os.fstat(fd))
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        except SapAccessError:
            raise
        except Exception:
            raise SapAccessError('SAP_AUDIT_UNAVAILABLE') from None
        finally:
            if fd is not None:
                os.close(fd)

    @staticmethod
    def _check_file(info):
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size > MAX_BYTES):
            raise SapAccessError('SAP_AUDIT_UNAVAILABLE')

    def _read(self):
        fd = None
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            self._check_file(os.fstat(fd))
            with os.fdopen(fd, 'r', encoding='utf-8') as stream:
                fd = None
                result = json.loads(stream.read(MAX_BYTES+1))
            if (set(result) != {'version', 'contracts', 'events'} or result['version'] != 1
                    or not isinstance(result['contracts'], dict) or not isinstance(result['events'], list)):
                raise ValueError()
            return result
        except FileNotFoundError:
            return {'version': 1, 'contracts': {}, 'events': []}
        except SapAccessError:
            raise
        except Exception:
            raise SapAccessError('SAP_AUDIT_UNAVAILABLE') from None
        finally:
            if fd is not None:
                os.close(fd)

    def read(self):
        with self._lock():
            return self._read()

    def record(self, event, *, contract=None):
        if set(event) - EVENT_FIELDS:
            raise SapAccessError('SAP_AUDIT_UNAVAILABLE')
        with self._lock():
            data = self._read()
            data['events'] = (data['events'] + [event])[-1000:]
            if contract is not None:
                # A changed target/credentials invalidate the old contract cache.
                data['contracts'] = {k: v for k, v in data['contracts'].items() if v['binding'] == event['binding']}
                data['contracts'][contract['function']] = {'binding': event['binding'],
                    'fetched_at': event['timestamp'], 'descriptor': contract}
            raw = json.dumps(data, ensure_ascii=False, sort_keys=True).encode('utf-8')
            if len(raw) > MAX_BYTES:
                raise SapAccessError('SAP_AUDIT_UNAVAILABLE')
            fd, temporary = tempfile.mkstemp(prefix='.sap-audit-', dir=str(Path(self.path).parent))
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                directory = os.open(str(Path(self.path).parent), os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
