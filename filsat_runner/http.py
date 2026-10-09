import json
import secrets
import urllib.error
import urllib.request
from urllib.parse import urlparse

MAX_RESPONSE = 32 * 1024 * 1024

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def request(url, data=None, headers=None, timeout=90, raw=False, method=None):
    headers = dict(headers or {})
    if isinstance(data, (dict, list)):
        data = json.dumps(data, ensure_ascii=False).encode()
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE + 1)
            if len(body) > MAX_RESPONSE:
                raise RuntimeError('Response exceeds the configured limit')
            return body if raw else json.loads(body)
    except urllib.error.HTTPError as error:
        # Never print server responses, tokens, URLs containing webhook secrets or customer inputs.
        raise RuntimeError(f'HTTP {error.code}') from None

class Client:
    def __init__(self, base_url, token):
        url = urlparse(base_url)
        if url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in ('127.0.0.1', 'localhost')):
            raise ValueError('Use HTTPS for the Filsat site')
        if url.username or url.password or url.query or url.fragment:
            raise ValueError('The site URL must not contain credentials or query parameters')
        self.base = base_url.rstrip('/') + '/api/runner'
        self.token = token

    def call(self, path, data=None, lease=None, raw=False, method=None):
        headers = {'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json'}
        if lease:
            headers['X-Job-Lease'] = lease
        return request(self.base + path, data, headers, raw=raw, method=method)

    def upload(self, order_id, lease, path):
        boundary = 'filsat' + secrets.token_hex(16)
        # Generated names only; original paths never enter HTTP headers.
        name = path.name.encode('ascii', 'replace').decode().replace('"', '_').replace('\r', '_').replace('\n', '_')
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
        body += path.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
        return request(self.base + f'/orders/{order_id}/files', body, {'Authorization': 'Bearer ' + self.token, 'X-Job-Lease': lease, 'Accept': 'application/json', 'Content-Type': 'multipart/form-data; boundary=' + boundary})
