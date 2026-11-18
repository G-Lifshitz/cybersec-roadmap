"""Bearer tokens: issued by the roadmap service at login, checked by both services.

Assignment 1 kept the login in a Flask session cookie. The UI is now served
from a different origin (the storage static website) than the services, and
browsers block third-party cookies, so the UI sends
`Authorization: Bearer <token>` instead.

A token is {"uid": user id, "ep": session_epoch}, signed with TOKEN_SECRET
(HMAC via itsdangerous, which ships with Flask) and valid for TOKEN_TTL_S.
Both services share TOKEN_SECRET, so progress verifies the signature itself
without calling roadmap on every request. Only roadmap can also check the
epoch against the database (a password change bumps it and revokes old
tokens); progress gets that check indirectly, because every progress write
first asks roadmap about the item with the same token (ADR 6).
"""
import os

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SALT = "cyberroadmap-auth"
DEFAULT_TTL_S = 12 * 60 * 60


class InvalidToken(Exception):
    pass


def _serializer():
    secret = os.environ.get("TOKEN_SECRET")
    if not secret or len(secret) < 32:
        # No fallback: a random per-process key would make the two services
        # disagree, and a hard-coded one would let anyone forge a login.
        raise RuntimeError("TOKEN_SECRET must be set (at least 32 characters)")
    return URLSafeTimedSerializer(secret, salt=SALT)


def issue(user_id, epoch):
    return _serializer().dumps({"uid": int(user_id), "ep": int(epoch)})


def verify(token):
    """Return (user_id, epoch) or raise InvalidToken."""
    ttl = int(os.environ.get("TOKEN_TTL_S", DEFAULT_TTL_S))
    try:
        data = _serializer().loads(token, max_age=ttl)
        return int(data["uid"]), int(data["ep"])
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError) as e:
        raise InvalidToken(str(e)) from None


def bearer(headers):
    """The token from an Authorization: Bearer header, or None."""
    value = headers.get("Authorization", "")
    scheme, _, token = value.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None
