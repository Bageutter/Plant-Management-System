"""Session + cross-service auth helpers.

vgarden has no login system of its own. A user's identity arrives via a
short-lived signed token minted by auth (see the /sso route in routes.py),
then lives in vgarden's own session cookie for the rest of the visit.
Server-to-server calls from auth (the /gardens API) authenticate with a
static shared-secret bearer token instead - see require_service_token.
"""

from functools import wraps

from flask import abort, current_app, redirect, request, session
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SSO_SALT = "vgarden-sso"
SSO_MAX_AGE_SECONDS = 60


def make_sso_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["INTER_SERVICE_SECRET"], salt=SSO_SALT)


def verify_sso_token(token: str) -> dict | None:
    try:
        return make_sso_serializer().loads(token, max_age=SSO_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None


def current_user_id() -> int | None:
    return session.get("user_id")


def require_login(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user_id() is None:
            return redirect(f"{current_app.config['AUTH_PUBLIC_URL']}/login")
        return view(*args, **kwargs)

    return wrapped


def require_garden_owner(garden) -> None:
    """Abort with 404 unless the current session belongs to this garden's owner.

    404 rather than 403 so a stranger can't use the response to tell a valid
    garden ID from a nonexistent one.
    """
    if garden is None or garden.owner_id != current_user_id():
        abort(404)


def require_service_token(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        expected = f"Bearer {current_app.config['INTER_SERVICE_SECRET']}"
        if request.headers.get("Authorization") != expected:
            abort(401)
        return view(*args, **kwargs)

    return wrapped
