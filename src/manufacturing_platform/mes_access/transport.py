"""Fixed-origin, node-affine, bounded HTTP session. No automatic retries."""
from html.parser import HTMLParser
from http.cookies import SimpleCookie
import http.client
import re
import queue
import socket
import ssl
import threading
import time
from urllib.parse import urlencode, urlsplit, urljoin

from .errors import MesAccessError


class _DeadlineHTTPSConnection(http.client.HTTPSConnection):
    """Expose the live TLS socket before its bounded handshake starts."""
    connect_deadline = None

    def _remaining_connect_time(self):
        remaining = self.connect_deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        return remaining

    def connect(self):
        http.client.HTTPConnection.connect(self)
        self.sock.settimeout(self._remaining_connect_time())
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host,
                                             do_handshake_on_connect=False)
        # Wrapping detaches the raw socket. Publish the SSLSocket above so the
        # watchdog can interrupt handshake work through the current conn.sock.
        self.sock.settimeout(self._remaining_connect_time())
        self.sock.do_handshake()


class _LoginPage(HTMLParser):
    def __init__(self):
        super().__init__(); self.sites=[]; self.item=None; self.form=False; self.fields={}

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='form' and attrs.get('method','').lower()=='post' and attrs.get('action') in {'j_spring_security_check','/j_spring_security_check'}:
            self.form=True
        if tag=='li' and re.fullmatch(r'[a-fA-F0-9]{32}',attrs.get('value','')):
            self.item=[attrs['value'],'']
        if tag=='input' and attrs.get('type')=='hidden':
            self.fields[attrs.get('name')]=attrs.get('value','')

    def handle_data(self, data):
        if self.item is not None: self.item[1]+=data

    def handle_endtag(self, tag):
        if tag=='li' and self.item is not None:
            self.sites.append((self.item[1].strip(),self.item[0])); self.item=None


class SessionTransport:
    def __init__(self, config, *, requester=None, resolver=socket.getaddrinfo, connection_factory=None):
        self.config=config
        self._requester=requester
        self._resolver=resolver
        self._connection_factory=connection_factory
        self._connection=None
        self._peer=None
        self._cookie=None
        self.authenticated=False
        self.response_bytes=0

    def close(self):
        self.authenticated=False; self._cookie=None
        if self._connection is not None:
            self._connection.close(); self._connection=None

    def _resolve_peer(self, host, port, deadline):
        # libc resolution cannot be cancelled portably. Only its daemon worker
        # may outlive the deadline; it cannot change session state or connect.
        result = queue.Queue(maxsize=1)

        def resolve():
            try:
                result.put((self._resolver(host, port, type=socket.SOCK_STREAM), None))
            except Exception as error:
                result.put((None, error))

        threading.Thread(target=resolve, daemon=True).start()
        try:
            addresses, error = result.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            raise TimeoutError() from None
        if time.monotonic() >= deadline:
            raise TimeoutError()
        if error is not None:
            raise error
        if not addresses:
            raise OSError()
        return addresses[0][4][0]

    def _native_request(self, method, path, body, headers):
        """DNS + initial connect share the connect budget; all request work,
        including headers/body, shares connect + read seconds of elapsed time.
        The read setting also remains an idle I/O cap. No phase is retried.
        """
        started = time.monotonic()
        connect_deadline = started + self.config.connect_timeout_seconds
        total_deadline = connect_deadline + self.config.read_timeout_seconds
        expired = threading.Event()
        active_socket = None
        response = None
        conn = self._connection
        timer = None

        def expire():
            expired.set()
            # HTTPResponse may own a detached socket (Connection: close).
            # shutdown interrupts blocked buffered header/body reads as well.
            sockets = [active_socket, getattr(conn, 'sock', None)]
            for sock in sockets:
                if sock is not None:
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    sock.close()

        def check(deadline):
            if expired.is_set() or time.monotonic() >= deadline:
                raise TimeoutError()

        def arm(deadline):
            watchdog = threading.Timer(max(0, deadline - time.monotonic()), expire)
            watchdog.daemon = True
            watchdog.start()
            return watchdog

        try:
            timer = arm(connect_deadline)
            url = urlsplit(self.config.base_url)
            port = url.port or (443 if url.scheme == 'https' else 80)
            if self._peer is None:
                self._peer = self._resolve_peer(url.hostname, port, connect_deadline)
            check(connect_deadline)
            if conn is None:
                if self._connection_factory:
                    conn = self._connection_factory(url, self._peer, self.config)
                elif url.scheme == 'https':
                    conn = _DeadlineHTTPSConnection(url.hostname, port,
                        context=ssl.create_default_context())
                else:
                    conn = http.client.HTTPConnection(url.hostname, port)
                self._connection = conn
                # Retain Host and certificate/SNI identity, even on reconnect.
                conn._create_connection = lambda address, timeout, source_address=None: socket.create_connection(
                    (self._peer, address[1]), timeout, source_address)
            conn.timeout = max(0.001, connect_deadline - time.monotonic())
            if isinstance(conn, _DeadlineHTTPSConnection):
                conn.connect_deadline = connect_deadline
            if conn.sock is None:
                conn.connect()
            active_socket = conn.sock
            check(connect_deadline)
            timer.cancel()
            timer = arm(total_deadline)
            active_socket.settimeout(min(self.config.read_timeout_seconds,
                                         max(0.001, total_deadline - time.monotonic())))
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            check(total_deadline)
            response_headers = response.getheaders()
            length = response.getheader('Content-Length')
            if length is not None and (not length.isdecimal() or int(length) > self.config.max_response_bytes):
                raise MesAccessError('MES_RESPONSE_TOO_LARGE', 502)
            if response.getheader('Content-Encoding', 'identity').lower() not in {'', 'identity'}:
                raise MesAccessError('MES_UNSUPPORTED_ENCODING', 502)
            payload = response.read(self.config.max_response_bytes + 1)
            check(total_deadline)
            return response.status, response_headers, payload
        except Exception:
            if expired.is_set():
                raise TimeoutError() from None
            raise
        finally:
            if timer is not None:
                timer.cancel()
            if response is not None:
                response.close()

    def _request(self, method, path, body=None, *, content_type='application/x-www-form-urlencoded'):
        if not self.config.enabled: raise MesAccessError('MES_DISABLED')
        if self.config.read_only is not True or self.config.version!=2: raise MesAccessError('MES_CONFIGURATION_ERROR')
        # Runtime callers cannot supply targets: only login and registry-built reads reach here.
        headers={'User-Agent':'Manufacturing-MES-ReadOnly/1.0','Accept-Encoding':'identity',
                 'Accept':'application/json,text/html;q=0.9'}
        if self._cookie: headers['Cookie']='JSESSIONID='+self._cookie
        if body is not None: headers['Content-Type']=content_type
        try:
            status, response_headers, payload=(self._requester or self._native_request)(method,path,body,headers)
            if type(payload) is not bytes or len(payload)>self.config.max_response_bytes:
                raise MesAccessError('MES_RESPONSE_TOO_LARGE',502)
            self.response_bytes+=len(payload)
            headers_lower={key.lower():value for key,value in response_headers}
            if headers_lower.get('content-encoding','identity').lower() not in {'','identity'}:
                raise MesAccessError('MES_UNSUPPORTED_ENCODING',502)
            for key,value in response_headers:
                if key.lower()!='set-cookie':continue
                cookie=SimpleCookie();cookie.load(value)
                if 'JSESSIONID' not in cookie:continue
                item=cookie['JSESSIONID']; host=urlsplit(self.config.base_url).hostname
                if (item['domain'] and item['domain'].lstrip('.').lower()!=host.lower()
                        or item['path'] and item['path']!='/'):
                    raise MesAccessError('MES_INVALID_COOKIE',502)
                if not re.fullmatch(r'[A-Za-z0-9._-]{1,256}',item.value):
                    raise MesAccessError('MES_INVALID_COOKIE',502)
                self._cookie=item.value
            return status,headers_lower,payload
        except MesAccessError:
            self.close();raise
        except (TimeoutError,socket.timeout):
            self.close();raise MesAccessError('MES_TIMEOUT',504) from None
        except ssl.SSLError:
            self.close();raise MesAccessError('MES_TLS_ERROR') from None
        except OSError:
            self.close();raise MesAccessError('MES_CONNECTION_FAILED') from None
        except Exception:
            self.close();raise MesAccessError('MES_TRANSPORT_ERROR') from None

    def _verify_home(self):
        status,_,body=self._request('GET','/')
        if (status!=200 or not self._cookie or not re.search(rb'<title>\s*I-Factory\s*</title>',body,re.I)
                or b'/core/home/home/show_subMenu.jsp' not in body):
            self.close();raise MesAccessError('MES_AUTHENTICATION_FAILED',502)
        self.authenticated=True
        return {'authentication_verified':True,'site_code':self.config.site_code,'source':'native_mes'}

    def login(self):
        if self.authenticated:return self._verify_home()
        status,_,body=self._request('GET','/login.jsp')
        if status!=200:raise MesAccessError('MES_LOGIN_CONTRACT_CHANGED',502)
        try:
            page=_LoginPage();page.feed(body.decode('utf-8'))
            sites=[site_id for code,site_id in page.sites if code==self.config.site_code]
            if (not page.form or len(sites)!=1 or page.fields.get('loginMode')!='default'
                    or self.config.site_id and self.config.site_id!=sites[0]):raise ValueError()
        except Exception:
            self.close();raise MesAccessError('MES_LOGIN_CONTRACT_CHANGED',502) from None
        form={'username':self.config.username,'password':self.config.password,
              'loginMode':self.config.login_mode,'siteId':sites[0]}
        status,headers,_=self._request('POST','/j_spring_security_check',urlencode(form).encode())
        redirect = headers.get('location', '')
        if not redirect.strip():
            self.close();raise MesAccessError('MES_AUTHENTICATION_FAILED',502)
        location=urlsplit(urljoin(self.config.base_url,redirect))
        origin=urlsplit(self.config.base_url)
        if (location.scheme,location.netloc)!=(origin.scheme,origin.netloc):
            self.close();raise MesAccessError('MES_REDIRECT_BLOCKED',502)
        if status!=302 or location.path!='/' or location.query or location.fragment:
            self.close();raise MesAccessError('MES_AUTHENTICATION_FAILED',502)
        return self._verify_home()

    def query(self, interface, filters=None, page=1, page_size=1):
        """Exactly one registered page; initial authentication only, no recovery."""
        import json
        from .registry import prepare_query

        spec, params = prepare_query(self.config, interface, filters, page, page_size)
        if not self.authenticated:
            self.login()
        encoded = json.dumps(params, separators=(',', ':'))
        if spec.encoding == 'json_body':
            target, body, content_type = spec.path, encoded.encode(), 'application/json'
        else:
            target = spec.path + '?' + urlencode({'paramJson': encoded})
            body, content_type = b'', 'application/x-www-form-urlencoded'
        try:
            status, headers, payload = self._request('POST', target, body, content_type=content_type)
            if status in {401, 403} or 300 <= status < 400:
                raise MesAccessError('MES_SESSION_EXPIRED', 502)
            if headers.get('location'):
                raise MesAccessError('MES_REDIRECT_BLOCKED', 502)
            if status != 200 or payload.lstrip().startswith(b'<'):
                raise MesAccessError('MES_INVALID_RESPONSE', 502)
            return payload
        except Exception:
            self.close()
            raise
