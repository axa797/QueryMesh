from api.auth import digest_api_key


def test_digest_is_deterministic() -> None:
    a = digest_api_key("secret-key", "pepper-x")
    b = digest_api_key("secret-key", "pepper-x")
    assert a == b
    assert len(a) == 64


def test_digest_changes_with_key_or_pepper() -> None:
    base = digest_api_key("k", "p")
    assert digest_api_key("k2", "p") != base
    assert digest_api_key("k", "p2") != base
