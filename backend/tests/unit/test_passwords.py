"""Password hashing tests."""

from app.auth.passwords import hash_password, verify_password


def test_hash_and_verify_round_trip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)


def test_wrong_password_fails() -> None:
    hashed = hash_password("correct horse battery staple")
    assert not verify_password("incorrect horse", hashed)


def test_malformed_hash_fails_closed() -> None:
    assert not verify_password("anything", "not-a-bcrypt-hash")
