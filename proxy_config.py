"""Validate operator-supplied SOCKS settings without resolution or secret-bearing errors."""
import ipaddress
import re
from urllib.parse import urlsplit, unquote


def parse_proxy(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048 or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError('invalid_proxy_config')
    try:
        if re.search(r'%(?![0-9a-fA-F]{2})', value):
            raise ValueError()
        uri = urlsplit(value)
        if uri.scheme not in ('socks5', 'socks5h') or uri.path not in ('', '/') or uri.query or uri.fragment:
            raise ValueError()
        host = str(ipaddress.ip_address(uri.hostname))
        if '%' in host or ipaddress.ip_address(host).is_unspecified or ipaddress.ip_address(host).is_multicast:
            raise ValueError()
        port = uri.port
        if not port or uri.username is None or uri.password is None:
            raise ValueError()
        user, password = unquote(uri.username, errors='strict'), unquote(uri.password, errors='strict')
        if any(not 0 < len(v.encode()) < 256 or any(ord(c) < 32 for c in v) for v in (user, password)):
            raise ValueError()
    except (ValueError, TypeError, UnicodeError):
        raise ValueError('invalid_proxy_config') from None
    # Both accepted schemes use remote target DNS in this architecture.
    return {'proxy_ip': host, 'proxy_port': port, 'username': user, 'password': password}
