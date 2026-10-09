"""Who is calling, without storing who they are.

The prototype has no accounts, so the daily chat limit is per client IP. The IP itself is
never stored: only HMAC-SHA256(pepper, ip), truncated. The pepper comes from IP_HASH_PEPPER;
without it a random one is made at start-up (limits then reset when the server restarts).
"""

import hashlib
import hmac
import logging
import secrets

log = logging.getLogger("api")

_fallback_pepper = None


def pepper(settings):
    global _fallback_pepper
    if settings.ip_hash_pepper:
        return settings.ip_hash_pepper.get_secret_value().encode()
    if _fallback_pepper is None:
        _fallback_pepper = secrets.token_bytes(32)
        log.warning("IP_HASH_PEPPER is not set; using a random one (chat limits reset on restart).")
    return _fallback_pepper


def client_ip(request, trust_proxy):
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def client_hash(request, settings):
    ip = client_ip(request, settings.trust_proxy_headers)
    return hmac.new(pepper(settings), ip.encode(), hashlib.sha256).hexdigest()[:32]
