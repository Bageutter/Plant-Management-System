import time

from itsdangerous import URLSafeTimedSerializer

import auth_utils


def test_verify_sso_token_round_trip(app):
    with app.app_context():
        token = auth_utils.make_sso_serializer().dumps({"user_id": 7, "email": "a@b.com"})
        data = auth_utils.verify_sso_token(token)
    assert data == {"user_id": 7, "email": "a@b.com"}


def test_verify_sso_token_rejects_garbage(app):
    with app.app_context():
        assert auth_utils.verify_sso_token("not-a-real-token") is None


def test_verify_sso_token_rejects_wrong_secret(app):
    with app.app_context():
        other = URLSafeTimedSerializer("a-different-secret", salt=auth_utils.SSO_SALT)
        token = other.dumps({"user_id": 1})
        assert auth_utils.verify_sso_token(token) is None


def test_verify_sso_token_rejects_expired(app, monkeypatch):
    with app.app_context():
        token = auth_utils.make_sso_serializer().dumps({"user_id": 1})
        monkeypatch.setattr(auth_utils, "SSO_MAX_AGE_SECONDS", 0)
        time.sleep(1.1)
        assert auth_utils.verify_sso_token(token) is None


def test_current_user_id_reads_session(app):
    with app.test_request_context():
        from flask import session

        assert auth_utils.current_user_id() is None
        session["user_id"] = 42
        assert auth_utils.current_user_id() == 42
