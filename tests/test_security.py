from gamenet.server.security.passwords import hash_secret, verify_secret


def test_hash_and_verify_roundtrip():
    hashed = hash_secret("1234")
    assert hashed != "1234"
    assert verify_secret("1234", hashed) is True


def test_wrong_secret_fails():
    hashed = hash_secret("1234")
    assert verify_secret("9999", hashed) is False


def test_unicode_pin():
    hashed = hash_secret("رمز۱۲۳۴🔒")
    assert verify_secret("رمز۱۲۳۴🔒", hashed) is True
    assert verify_secret("رمز۱۲۳۴", hashed) is False


def test_long_pin_over_bcrypt_limit():
    # 100 chars (> 72 bytes): must not raise, and full secret must matter.
    pin = "a" * 100
    hashed = hash_secret(pin)
    assert verify_secret(pin, hashed) is True
    assert verify_secret("a" * 99 + "b", hashed) is False


def test_invalid_hash_never_raises():
    assert verify_secret("1234", "not-a-valid-hash") is False
    assert verify_secret("1234", "") is False


def test_hashes_are_salted():
    assert hash_secret("1234") != hash_secret("1234")
