"""Metadata in app config; secrets exclusively in the native OS keychain."""

import json
import sys
from pathlib import Path
from typing import Any, Protocol

from oracle.auth.contracts import Profile

SERVICE = "oracle-studio"


class Vault(Protocol):
    def get_password(self, service: str, account: str) -> str | None: ...
    def set_password(self, service: str, account: str, password: str) -> None: ...
    def delete_password(self, service: str, account: str) -> None: ...


class NativeVault:
    def _backend(self) -> Any:
        import keyring

        backend = keyring.get_keyring()
        if sys.platform != "win32" or not type(backend).__module__.startswith(
            "keyring.backends.Windows"
        ):
            raise RuntimeError("Native Windows Credential Manager is unavailable")
        return backend

    def get_password(self, service: str, account: str) -> str | None:
        value = self._backend().get_password(service, account)
        return value if isinstance(value, str) else None

    def set_password(self, service: str, account: str, password: str) -> None:
        self._backend().set_password(service, account, password)

    def delete_password(self, service: str, account: str) -> None:
        self._backend().delete_password(service, account)


class ProfileStore:
    def __init__(self, path: Path, vault: Vault | None = None) -> None:
        self.path, self.vault = path, vault or NativeVault()

    def read(self) -> tuple[list[Profile], str]:
        if not self.path.exists():
            return [], ""
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return [Profile.model_validate(p) for p in payload.get("profiles", [])], str(
            payload.get("lastServer", "")
        )

    @staticmethod
    def key(profile: Profile) -> str:
        return f"{profile.server}:{profile.login}:{profile.password_type}"

    def save(self, profile: Profile, password: str) -> None:
        profiles, _ = self.read()
        key = self.key(profile)
        previous = self.vault.get_password(SERVICE, key)
        self.vault.set_password(SERVICE, key, password)
        profiles = [p for p in profiles if self.key(p) != self.key(profile)]
        profiles.insert(0, profile)
        try:
            self._write(profiles, profile.server)
        except Exception:
            if previous is None:
                self.vault.delete_password(SERVICE, key)
            else:
                self.vault.set_password(SERVICE, key, previous)
            raise

    def remember_server(self, server: str) -> None:
        profiles, _ = self.read()
        self._write(profiles, server)

    def _write(self, profiles: list[Profile], server: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "profiles": [p.model_dump(mode="json", by_alias=True) for p in profiles],
                    "lastServer": server,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def password(self, profile: Profile) -> str | None:
        return self.vault.get_password(SERVICE, self.key(profile))
