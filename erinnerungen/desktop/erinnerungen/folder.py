"""Local folder mode (fallback when no server is reachable).

Each list is one .ics file directly in the chosen folder. Writes are atomic
(tmp file + rename). The "etag" is mtime:size – good enough for a local folder.
"""
from __future__ import annotations

import contextlib
import os
import re
import tempfile
from dataclasses import dataclass

from . import ics


class ConflictError(Exception):
    pass


@dataclass
class RemoteItem:
    href: str  # Dateiname
    etag: str
    data: str


class FolderBackend:
    def __init__(self, root: str):
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    def _path(self, name: str) -> str:
        if not name.endswith(".ics"):
            name += ".ics"
        if os.path.basename(name) != name or name in (".", ".."):
            raise ValueError(f"Invalid file name: {name!r}")
        return os.path.join(self.root, name)

    @staticmethod
    def _slug(name: str) -> str:
        slug = re.sub(r"[^\w\-]+", "-", name.strip().lower()).strip("-") or "liste"
        return slug

    def _etag_of(self, path: str) -> str:
        st = os.stat(path)
        return f"{int(st.st_mtime)}:{st.st_size}"

    def discover_lists(self) -> list[tuple[str, str]]:
        out = []
        for fn in sorted(os.listdir(self.root)):
            if fn.lower().endswith(".ics"):
                path = os.path.join(self.root, fn)
                try:
                    with open(path, encoding="utf-8", newline="") as f:
                        props = ics.parse_calendar_props(f.read())
                except OSError:
                    continue
                out.append((fn, props.get(ics.LIST_NAME_PROP, fn[:-4])))
        return out

    def list_file_for(self, name: str) -> str:
        return self._slug(name) + ".ics"

    def ensure_list(self, path: str | None, name: str, color: str | None = None, icon: str | None = None) -> str:
        fname = path or self.list_file_for(name)
        full = self._path(fname)
        if not os.path.exists(full):
            text = ics.serialize_calendar([], name=name, color=color, icon=icon)
            self._write_atomic(full, text)
        return fname

    def fetch_tasks(self, fname: str) -> list[RemoteItem]:
        full = self._path(fname)
        if not os.path.exists(full):
            return []
        with open(full, encoding="utf-8", newline="") as f:
            text = f.read()
        return [
            RemoteItem(href=uid + ".ics", etag=self._etag_of(full), data=block)
            for uid, block in ics.vtodo_blocks(text)
        ]

    def _read(self, fname: str) -> str:
        with open(self._path(fname), encoding="utf-8", newline="") as f:
            return f.read()

    def _write_atomic(self, full: str, text: str) -> None:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(full), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            os.replace(tmp, full)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def upload(self, fname: str, uid: str, vtodo_block: str, etag: str | None) -> str:
        full = self._path(fname)
        if not os.path.exists(full):
            raise FileNotFoundError(full)
        if etag and etag != self._etag_of(full):
            raise ConflictError("File was changed in the meantime")
        text = self._read(fname)
        new_text = ics.replace_vtodo_block(text, uid, vtodo_block)
        self._write_atomic(full, new_text)
        return self._etag_of(full)

    def remove(self, fname: str, uid: str, etag: str | None) -> None:
        full = self._path(fname)
        if not os.path.exists(full):
            return
        if etag and etag != self._etag_of(full):
            raise ConflictError("File was changed in the meantime")
        text = self._read(fname)
        self._write_atomic(full, ics.remove_vtodo_block(text, uid))

    def delete_list_file(self, fname: str) -> None:
        full = self._path(fname)
        if os.path.exists(full):
            os.unlink(full)
