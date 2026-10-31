"""Пароли, атомарное сохранение и отзыв сессий web-редактора."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.app.web_access import AccessDenied, AccessLimited, WebAccess


PASSWORD = "test-password-059"


def enable(access):
    return access.update({"enabled": True, "username": "owner", "password": PASSWORD})[1]


def test_default_open_and_persistent_account(tmp_path):
    access = WebAccess(tmp_path)
    assert access.authorized("")
    token = enable(access)
    assert access.authorized(token) and not access.authorized("")
    assert PASSWORD not in access.path.read_text()
    assert set(access.status()) == {"enabled", "configured", "username"}
    reopened = WebAccess(tmp_path)
    assert reopened.status()["enabled"]
    assert not reopened.authorized(token)
    assert reopened.authorized(reopened.login("owner", PASSWORD))
    with pytest.raises(AccessDenied):
        reopened.login("owner", "wrong")


def test_change_disable_and_reenable_require_current_password(tmp_path):
    access = WebAccess(tmp_path)
    token = enable(access)
    with pytest.raises(AccessDenied):
        access.update({"enabled": False}, token)
    _, replacement = access.update({"enabled": True, "username": "new-owner", "password": "new-password-059",
                                    "current_password": PASSWORD}, token)
    assert not access.authorized(token)
    assert access.authorized(replacement)
    with pytest.raises(AccessDenied):
        access.update({"enabled": False, "current_password": PASSWORD}, replacement)
    access.update({"enabled": False, "current_password": "new-password-059"}, replacement)
    assert access.authorized("")
    with pytest.raises(AccessDenied):
        access.update({"enabled": True})
    access.update({"enabled": True, "current_password": "new-password-059"})
    assert not access.authorized("")


def test_invalid_setup_and_failed_write_preserve_state(tmp_path, monkeypatch):
    access = WebAccess(tmp_path)
    for body in [{"enabled": True}, {"enabled": True, "username": "owner", "password": "short"}, {"enabled": "false"}]:
        with pytest.raises(ValueError):
            access.update(body)
    assert not access.path.exists()
    token = enable(access)
    original = access.path.read_bytes()
    def fail(_):
        raise OSError("read-only")
    monkeypatch.setattr(access, "_save", fail)
    with pytest.raises(OSError):
        access.update({"enabled": False, "current_password": PASSWORD}, token)
    assert access.authorized(token) and access.status()["enabled"]
    assert access.path.read_bytes() == original


@pytest.mark.parametrize("content", ["bad json", '{}', '{"schema":1,"enabled":true}',
    '{"schema":1,"enabled":"false"}',
    json.dumps({"schema":1,"enabled":False,"username":"owner","salt":"x","password_hash":"x"})])
def test_corrupt_record_fails_closed(tmp_path, content):
    (tmp_path / "web-access.json").write_text(content)
    with pytest.raises(RuntimeError):
        WebAccess(tmp_path)


def test_sessions_expire_and_attempts_are_bounded(tmp_path, monkeypatch):
    access = WebAccess(tmp_path)
    token = enable(access)
    access._sessions[token] = 0
    assert not access.authorized(token)
    for _ in range(10):
        with pytest.raises(AccessDenied):
            access.login("owner", "wrong")
    with pytest.raises(AccessLimited):
        access.login("owner", PASSWORD)


def test_concurrent_changes_cannot_reuse_revoked_session(tmp_path):
    access = WebAccess(tmp_path)
    token = enable(access)
    def update(index):
        try:
            access.update({"enabled": True, "username": f"owner-{index}", "current_password": PASSWORD}, token)
            return True
        except AccessDenied:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(update, [1, 2])) == 1
