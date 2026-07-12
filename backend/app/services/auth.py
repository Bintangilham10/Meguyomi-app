from hmac import compare_digest

from pwdlib import PasswordHash

from app.core.config import Settings


password_hash = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$JJsgtT5z5+neM/k5hS1+jg$"
    "CFAKkq/ZOtKk/e1QiFm/KkEPBxYjw7x+6Sc2RJQsAxw"
)


def authenticate_admin(username: str, password: str, settings: Settings) -> bool:
    username_matches = compare_digest(username, settings.admin_username)
    configured_hash = settings.admin_password_hash
    hash_to_verify = (
        configured_hash if configured_hash.startswith("$argon2") else DUMMY_PASSWORD_HASH
    )

    try:
        password_matches = password_hash.verify(password, hash_to_verify)
    except (TypeError, ValueError):
        password_matches = False

    return bool(configured_hash) and username_matches and password_matches
