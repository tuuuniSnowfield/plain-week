"""Password storage via the Secret Service (libsecret/GNOME Keyring).

The password is never written in plaintext to GSettings/DB/files.
If no Secret Service is available (e.g. headless), SecretsUnavailable is raised –
the app then asks at every start (prompt) instead of storing.
"""
from __future__ import annotations


class SecretsUnavailable(Exception):
    pass


def _service(app_id: str):
    try:
        import gi

        gi.require_version("Secret", "1")
        from gi.repository import Secret

        schema = Secret.Schema.new(
            "erinnerungen", Secret.SchemaFlags.NONE,
            Secret.SchemaAttributeType.STRING, "app_id",
            Secret.SchemaAttributeType.STRING, "username",
        )
        return Secret, schema
    except Exception as exc:  # noqa: BLE001
        raise SecretsUnavailable(f"Secret Service unavailable: {exc}") from exc


def store_password(app_id: str, username: str, password: str) -> None:
    Secret, schema = _service(app_id)
    Secret.password_store_sync(
        schema,
        {"app_id": app_id, "username": username},
        Secret.COLLECTION_DEFAULT,
        f"{app_id} – CalDAV",
        password,
        None,
    )


def load_password(app_id: str, username: str) -> str | None:
    Secret, schema = _service(app_id)
    return Secret.password_lookup_sync(
        schema, {"app_id": app_id, "username": username}, None
    )


def delete_password(app_id: str, username: str) -> None:
    Secret, schema = _service(app_id)
    Secret.password_clear_sync(
        schema, {"app_id": app_id, "username": username}, None
    )
