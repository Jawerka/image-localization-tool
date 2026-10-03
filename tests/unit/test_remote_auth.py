"""Коды сопряжения, хеши токенов, отзыв устройства и лимит запросов."""

import sys
import types

import pytest

from src.app.remote_auth import (
    DEFAULT_CODE_TTL,
    DEFAULT_RATE_LIMIT,
    DEFAULT_RATE_WINDOW,
    Device,
    Pairing,
    RateLimiter,
    find_device,
    forget_hash,
    hash_token,
    make_device,
    remember_hash,
    revoke,
    token_matches,
)


class _Clock:
    def __init__(self, now: float):
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def keyring_stub(monkeypatch):
    """Подмена keyring, чтобы тесты не писали в системное хранилище."""
    bag: dict[tuple[str, str], str] = {}
    module = types.ModuleType("keyring")

    def set_password(service, username, value):
        bag[(service, username)] = value

    def delete_password(service, username):
        bag.pop((service, username), None)

    module.set_password = set_password
    module.delete_password = delete_password
    module.bag = bag
    monkeypatch.setitem(sys.modules, "keyring", module)
    return module


def test_issue_code_and_redeem(monkeypatch):
    monkeypatch.setattr("src.app.remote_auth.secrets.randbelow", lambda _bound: 42)
    pairing = Pairing(clock=_Clock(1000.0))
    code = pairing.issue_code()
    assert code == "000042"
    assert len(code) == 6 and code.isdigit()
    token = pairing.redeem(code)
    assert token
    assert token != code


def test_hash_token_and_matches():
    token = "device-token"
    digest = hash_token(token)
    assert len(digest) == 64
    assert all(char in "0123456789abcdef" for char in digest)
    assert token_matches(token, digest) is True
    assert token_matches("other-token", digest) is False
    assert token_matches("", digest) is False
    assert token_matches(token, "") is False


def test_expired_code():
    clock = _Clock(1000.0)
    pairing = Pairing(clock=clock)
    code = pairing.issue_code()
    clock.now += 301
    assert pairing.redeem(code) is None


def test_reused_code():
    pairing = Pairing(clock=_Clock(1000.0))
    code = pairing.issue_code()
    token = pairing.redeem(code)
    assert token
    assert pairing.redeem(code) is None
    assert token_matches(token, hash_token(token)) is True


def test_wrong_code_does_not_burn():
    pairing = Pairing(clock=_Clock(1000.0))
    code = pairing.issue_code()
    wrong = "000000" if code != "000000" else "000001"
    assert pairing.redeem(wrong) is None
    token = pairing.redeem(code)
    assert token
    assert token != code


def test_new_code_replaces_unused(monkeypatch):
    issued = iter((1, 2))
    monkeypatch.setattr("src.app.remote_auth.secrets.randbelow", lambda _bound: next(issued))
    pairing = Pairing(clock=_Clock(1000.0))
    first = pairing.issue_code()
    second = pairing.issue_code()
    assert first == "000001"
    assert second == "000002"
    assert pairing.redeem(first) is None
    assert pairing.redeem(second)


def test_revoke_drops_device():
    token = "raw-token"
    other_token = "other-token"
    clock = _Clock(10.0)
    device = make_device(token, name="phone", clock=clock)
    other = make_device(other_token, name="tablet", clock=clock)
    remaining = revoke([device.to_dict(), other], device.id)
    assert all(isinstance(item, Device) for item in remaining)
    assert [item.id for item in remaining] == [other.id]
    assert find_device(remaining, token) is None
    assert find_device(remaining, other_token) == other
    kept = revoke(remaining, "missing-id")
    assert [item.id for item in kept] == [other.id]


def test_rate_limiter():
    assert DEFAULT_RATE_LIMIT == 30
    assert DEFAULT_RATE_WINDOW == 60.0
    clock = _Clock(10_000.0)
    limiter = RateLimiter(clock=clock)
    assert limiter.allow("") is False
    assert all(limiter.allow("token") for _ in range(30))
    assert limiter.allow("token") is False
    assert limiter.allow("other") is True
    clock.now += 30
    assert limiter.allow("token") is False
    clock.now += 30
    assert limiter.allow("token") is True


def test_rejected_call_is_not_counted():
    clock = _Clock(0.0)
    limiter = RateLimiter(limit=1, window=60.0, clock=clock)
    assert limiter.allow("k") is True
    clock.now = 30.0
    assert limiter.allow("k") is False
    clock.now = 60.0
    assert limiter.allow("k") is True


def test_make_device_omits_raw_token():
    token = "raw-secret-token"
    device = make_device(token, name="laptop", clock=_Clock(42.0))
    payload = device.to_dict()
    assert set(payload) == {"id", "name", "token_hash", "created"}
    assert payload["name"] == "laptop"
    assert payload["created"] == 42.0
    assert payload["token_hash"] == hash_token(token)
    blob = "".join(str(value) for value in payload.values())
    assert token not in blob
    assert Device.from_dict(payload) == device
    assert find_device([payload], token) == device
    assert len(device.id) == 32


def test_keyring_stores_hash_only(keyring_stub):
    token = "raw-token"
    device = make_device(token, name="phone", clock=_Clock(1.0))
    assert remember_hash(device.id, device.token_hash) is True
    stored = keyring_stub.bag[("ImageLocalizationTool", f"remote:{device.id}")]
    assert stored == hash_token(token)
    assert token not in stored
    assert revoke([device], device.id) == []
    assert ("ImageLocalizationTool", f"remote:{device.id}") not in keyring_stub.bag


def test_keyring_errors_are_soft(monkeypatch):
    module = types.ModuleType("keyring")

    def boom(*_args, **_kwargs):
        raise RuntimeError("no keyring")

    module.set_password = boom
    module.delete_password = boom
    monkeypatch.setitem(sys.modules, "keyring", module)
    assert remember_hash("dev", hash_token("tok")) is False
    forget_hash("dev")

    monkeypatch.setitem(sys.modules, "keyring", None)
    assert remember_hash("dev", "abc") is False
    forget_hash("dev")


def test_current_code_reads_stored_code(monkeypatch):
    issued = iter((7,))
    monkeypatch.setattr(
        "src.app.remote_auth.secrets.randbelow",
        lambda _bound: next(issued),
    )
    pairing = Pairing(clock=_Clock(1000.0))
    assert pairing.current_code() is None

    code = pairing.issue_code()
    assert code == "000007"
    assert pairing.current_code() == code
    assert pairing.current_code() == code

    assert pairing.redeem(code)
    assert pairing.current_code() is None


def test_current_code_expired():
    clock = _Clock(1000.0)
    pairing = Pairing(clock=clock)
    code = pairing.issue_code()
    clock.now = 1000.0 + DEFAULT_CODE_TTL - 1
    assert pairing.current_code() == code
    clock.now = 1000.0 + DEFAULT_CODE_TTL
    assert pairing.current_code() is None


def test_code_expires_at_ttl():
    assert DEFAULT_CODE_TTL == 300.0
    clock = _Clock(1000.0)
    alive = Pairing(clock=clock)
    code = alive.issue_code()
    clock.now = 1000.0 + DEFAULT_CODE_TTL - 1
    assert alive.redeem(code)

    clock.now = 1000.0
    expired = Pairing(clock=clock)
    code = expired.issue_code()
    clock.now = 1000.0 + DEFAULT_CODE_TTL
    assert expired.redeem(code) is None
