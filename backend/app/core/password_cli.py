from getpass import getpass

from pwdlib import PasswordHash


def main() -> None:
    password = getpass("Password admin: ")
    confirmation = getpass("Ulangi password: ")
    if not password or password != confirmation:
        raise SystemExit("Password kosong atau konfirmasi tidak sama.")
    print(PasswordHash.recommended().hash(password))


if __name__ == "__main__":
    main()
