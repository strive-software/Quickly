"""Keep JWT verification constrained to the configured symmetric algorithm."""
import pytest
from fastapi import HTTPException
from app import auth


def test_session_tokens_reject_other_algorithms_and_tampering(monkeypatch):
    monkeypatch.setattr(auth, 'SECRET_KEY', 'isolated-test-key-' * 4)
    access = auth.create_access_token(7, 'admin')
    assert auth.decode_token(access)['sub'] == '7'
    other_algorithm = auth.jwt.encode({'sub': '7', 'type': 'access'}, auth.SECRET_KEY, algorithm='HS384')
    for invalid in (other_algorithm, access[:-8] + 'tampered'):
        with pytest.raises(HTTPException) as error:
            auth.decode_token(invalid)
        assert error.value.status_code == 401
