"""Server-only MES settings. Configuration loading never connects to MES."""
from dataclasses import dataclass, field
import hashlib
import json
import os
import re
import stat
from urllib.parse import urlsplit


@dataclass(frozen=True)
class MesConnectionConfig:
    version: int
    system: str
    base_url: str
    environment: str
    username: str = field(repr=False)
    password: str = field(repr=False)
    enabled: bool
    read_only: bool
    allowed_api_paths: tuple[str, ...]
    connect_timeout_seconds: int
    read_timeout_seconds: int
    login_mode: str = 'default'
    site_id: str | None = None
    allow_http_production: bool = False
    site_code: str = '1000'
    max_response_bytes: int = 2 * 1024 * 1024
    max_rows: int = 5

    def summary(self):
        return {'configuration_valid': True, 'version': self.version, 'system': 'mes',
                'base_url': self.base_url, 'environment': self.environment,
                'enabled': self.enabled, 'read_only': self.read_only, 'site_code': self.site_code,
                'credentials_configured': bool(self.username and self.password),
                'authentication_verified': False, 'allowed_path_count': len(self.allowed_api_paths),
                'max_rows': self.max_rows}

    def fingerprint(self):
        # The digest remains in private audit storage and is never projected.
        fields = {name: getattr(self, name) for name in self.__dataclass_fields__}
        return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError()
        result[key] = value
    return result


def _validate(raw):
    base = {'version','system','base_url','environment','username','password','authentication',
            'enabled','read_only','allowed_api_paths','connect_timeout_seconds','read_timeout_seconds'}
    extra = {'allow_http_production','site_code','max_response_bytes','max_rows'}
    if type(raw) is not dict or type(raw.get('version')) is not int or raw['version'] not in {1,2}:
        raise ValueError()
    if set(raw) != (base | extra if raw['version'] == 2 else base): raise ValueError()
    if raw['system'] != 'mes' or raw['environment'] not in {'production','test','development'}: raise ValueError()
    origin = raw['base_url']
    if not isinstance(origin, str) or len(origin)>300 or re.search(r'[\s\\\x00-\x1f]', origin): raise ValueError()
    url = urlsplit(origin)
    if (url.scheme not in {'http','https'} or not url.hostname or url.username is not None
            or url.password is not None or url.path not in {'','/'} or url.query or url.fragment): raise ValueError()
    if url.port is not None and not 1 <= url.port <= 65535: raise ValueError()
    if not re.fullmatch(r'[A-Za-z0-9.:-]+', url.hostname): raise ValueError()
    if type(raw['enabled']) is not bool or raw['read_only'] is not True: raise ValueError()
    if (raw['enabled'] and raw['environment'] == 'production'
            and origin not in {'http://mes.orbbec.com/', 'https://mes.orbbec.com/'}): raise ValueError()
    for key in ('username','password'):
        if not isinstance(raw[key],str) or len(raw[key])>2048: raise ValueError()
    if raw['username'] and (raw['username'] != raw['username'].strip() or '\x00' in raw['username']): raise ValueError()
    if raw['enabled'] and not (raw['username'] and raw['password']): raise ValueError()
    paths = raw['allowed_api_paths']
    if (not isinstance(paths,list) or len(paths)>20 or len(set(paths)) != len(paths)
            or any(not isinstance(p,str) or not re.fullmatch(r'/[A-Za-z0-9_/!.-]+\.action',p)
                   or '..' in p for p in paths)): raise ValueError()
    for key in ('connect_timeout_seconds','read_timeout_seconds'):
        if type(raw[key]) is not int or not 1 <= raw[key] <= 30: raise ValueError()
    auth=raw['authentication']
    expected={'mode':'form_session','status':'not_verified','login_path':'/j_spring_security_check',
              'username_field':'username','password_field':'password','session_cookie_name':'JSESSIONID'}
    if type(auth) is not dict or set(auth) != set(expected)|{'additional_form_fields'}: raise ValueError()
    if any(auth[k] != v for k,v in expected.items()): raise ValueError()
    form=auth['additional_form_fields']
    if type(form) is not dict or set(form) != {'loginMode','siteId'} or form['loginMode'] not in {None,'default'}: raise ValueError()
    if form['siteId'] is not None and (not isinstance(form['siteId'],str) or not re.fullmatch(r'[a-fA-F0-9]{32}',form['siteId'])): raise ValueError()
    defaults={'allow_http_production':False,'site_code':'1000','max_response_bytes':2*1024*1024,'max_rows':5}
    limits={**defaults,**{k:raw[k] for k in extra if k in raw}}
    if type(limits['allow_http_production']) is not bool: raise ValueError()
    if not isinstance(limits['site_code'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,32}',limits['site_code']): raise ValueError()
    for key,lo,hi in [('max_rows',1,5),('max_response_bytes',1024,2*1024*1024)]:
        if type(limits[key]) is not int or not lo <= limits[key] <= hi: raise ValueError()
    if raw['version']==1 and raw['enabled']: raise ValueError()
    if raw['enabled'] and url.scheme=='http' and raw['environment']=='production' and not limits['allow_http_production']: raise ValueError()
    value={k:v for k,v in raw.items() if k not in {'authentication',*extra}}
    return MesConnectionConfig(**{**value,'base_url':origin.rstrip('/')+'/',
        'allowed_api_paths':tuple(paths),'login_mode':form['loginMode'] or 'default','site_id':form['siteId'],**limits})


def load_mes_connection_config(path):
    descriptor=None
    try:
        if not isinstance(path,str) or not os.path.isabs(path): raise ValueError()
        descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        info=os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid not in {0,os.geteuid()} or info.st_mode & 0o077
                or info.st_nlink != 1 or info.st_size>128*1024): raise ValueError()
        with os.fdopen(descriptor,'r',encoding='utf-8') as stream:
            descriptor=None; value=stream.read(128*1024+1)
        if len(value.encode())>128*1024: raise ValueError()
        return _validate(json.loads(value,object_pairs_hook=_unique))
    except Exception:
        raise ValueError('invalid MES connection configuration') from None
    finally:
        if descriptor is not None: os.close(descriptor)
