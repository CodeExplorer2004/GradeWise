from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_and_verification() -> None:
    password_hash = hash_password("A-strong-demo-password")

    assert password_hash != "A-strong-demo-password"
    assert verify_password("A-strong-demo-password", password_hash)
    assert not verify_password("wrong-password", password_hash)


def test_access_token_round_trip() -> None:
    token = create_access_token(42)

    assert decode_token(token, "access") == 42
