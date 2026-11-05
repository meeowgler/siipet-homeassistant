"""Tests for the SiiPet sign-in helpers."""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pytest

from custom_components.siipet.api import Session, SiiPetError
from custom_components.siipet.api.auth import (
    encrypt_challenge,
    hash_password,
    needs_renewal,
    read_token_payload,
)
from custom_components.siipet.api.challenge_key import CHALLENGE_KEY

from ..common import load_data

TEST_KEY = bytes(range(32))
TEST_NONCE = bytes(range(12))
VERIFY_CODE = "0123456789abcdef0123456789abcdef"


def test_challenge_key_size() -> None:
    """The bundled key is an AES-256 key."""
    assert len(CHALLENGE_KEY) == 32


def test_encrypt_challenge_round_trip() -> None:
    """The output is base64 of nonce, ciphertext, and tag, and it decrypts."""
    raw = base64.b64decode(encrypt_challenge(VERIFY_CODE, key=TEST_KEY))
    assert len(raw) == 12 + len(VERIFY_CODE) + 16
    assert AESGCM(TEST_KEY).decrypt(raw[:12], raw[12:], None).decode() == VERIFY_CODE


def test_encrypt_challenge_known_answer() -> None:
    """A fixed key and nonce give the output of an independent AES-GCM library."""
    # Computed once with pycryptodome for TEST_KEY, TEST_NONCE, and VERIFY_CODE.
    expected = "AAECAwQFBgcICQoLdzPkKPHQ9Cy1ePbp0o0dC7PntQfETmlLAF6E534NZdTkcFnQofHtpQ5IF+ONTDMf"
    assert encrypt_challenge(VERIFY_CODE, key=TEST_KEY, nonce=TEST_NONCE) == expected


def test_encrypt_challenge_random_nonce() -> None:
    """Two calls use different nonces."""
    assert encrypt_challenge(VERIFY_CODE, key=TEST_KEY) != encrypt_challenge(
        VERIFY_CODE, key=TEST_KEY
    )


def test_read_token_payload() -> None:
    """The payload gives UserId and exp."""
    payload = read_token_payload(load_data("login.json")["Token"])
    assert payload == {"UserId": "user-0001", "exp": 1792972800}


@pytest.mark.parametrize("token", ["", "not-a-jwt", "a.!!!.c", "a.bnVsbA.c"])
def test_read_token_payload_invalid(token: str) -> None:
    """A token without a JSON object payload raises SiiPetError."""
    with pytest.raises(SiiPetError):
        read_token_payload(token)


def test_session_user_id() -> None:
    """The session reads UserId from its token."""
    data = load_data("login.json")
    assert Session(data["Token"], data["ExpireAt"]).user_id == "user-0001"


@pytest.mark.parametrize(
    ("now_ms", "expected"),
    [
        (1_000_000_000 - 86_400_000, False),
        (1_000_000_000 - 86_400_000 + 1, True),
        (1_000_000_000, True),
    ],
)
def test_needs_renewal(now_ms: int, expected: bool) -> None:
    """Renewal starts when less than one day remains before ExpireAt."""
    assert needs_renewal(1_000_000_000, now_ms) is expected


def test_hash_password() -> None:
    """The password is sent as the lowercase SHA-256 hex digest of its UTF-8 bytes."""
    assert hash_password("password") == (
        "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"
    )
    # Non-ASCII text is hashed as UTF-8.
    assert hash_password("kot żółty") == (
        "d68275a2f2e64cd355d75d50b9db35da25ab7e64628d992d7e9070efdbae2a31"
    )
