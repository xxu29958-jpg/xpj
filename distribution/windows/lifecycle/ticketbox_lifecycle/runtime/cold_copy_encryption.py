"""C1 v1 wire format (big endian): header, header tag, contiguous AES-GCM frames.

The version fixes the KDF and frame size. Nonce = random prefix || u32 index ||
final byte. Index zero authenticates the header; data frames start at one.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from ticketbox_lifecycle.domain.encrypted_cold_copy import recovery_identity, recovery_point, recovery_result
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.cold_archive import verify_archive
from ticketbox_lifecycle.runtime.windows_cold_file import create_private_archive, open_cold_source

MAGIC = b"TBXCENC\x01"
HEADER = struct.Struct(">8s16s7sQ")  # version, salt, nonce prefix, plaintext length
CHUNK = 1024 * 1024
TAG = 16
_POSITION = struct.Struct(">IB")


def _invalid() -> LifecycleError:
    return LifecycleError("cold_authentication_failed", "encrypted cold copy authentication failed")


@dataclass(frozen=True)
class _Frames:
    header: bytes
    size: int
    prefix: bytes
    cipher: AESGCM
    header_digest: bytes

    @classmethod
    def from_header(cls, header: bytes, secret: bytes) -> _Frames:
        if len(header) != HEADER.size or not secret:
            raise _invalid()
        magic, salt, prefix, size = HEADER.unpack(header)
        if magic != MAGIC or size > 0xFFFFFFFF * CHUNK:
            raise _invalid()
        key = Argon2id(salt=salt, length=32, iterations=3, lanes=4, memory_cost=65536).derive(secret)
        return cls(header, size, prefix, AESGCM(key), hashlib.sha256(header).digest())

    @property
    def count(self) -> int:
        return max(1, (self.size + CHUNK - 1) // CHUNK)

    @property
    def encrypted_size(self) -> int:
        return HEADER.size + TAG + self.size + self.count * TAG

    def frame(self, index: int) -> tuple[int, bytes, bytes]:
        position = _POSITION.pack(index + 1, index == self.count - 1)
        return min(CHUNK, self.size - index * CHUNK), self.prefix + position, self.header_digest + position


def _seal(source: BinaryIO, output: BinaryIO, frames: _Frames) -> str:
    output.write(frames.header)
    output.write(frames.cipher.encrypt(frames.prefix + bytes(5), b"", frames.header))
    digest = hashlib.sha256()
    for index in range(frames.count):
        size, nonce, aad = frames.frame(index)
        chunk = source.read(size)
        if len(chunk) != size:
            raise LifecycleError("cold_source_changed", "cold copy size changed during encryption")
        digest.update(chunk)
        output.write(frames.cipher.encrypt(nonce, chunk, aad))
    if source.read(1):
        raise LifecycleError("cold_source_changed", "cold copy grew during encryption")
    return digest.hexdigest()


class _AuthenticatedReader(io.RawIOBase):
    """Seekable ZIP input. Authenticate each entire frame before exposing any of it."""

    def __init__(self, source: BinaryIO, secret: bytes):
        self.source = source
        source.seek(0)
        self.frames = frames = _Frames.from_header(source.read(HEADER.size), secret)
        try:
            frames.cipher.decrypt(frames.prefix + bytes(5), source.read(TAG), frames.header)
        except InvalidTag as exc:
            raise _invalid() from exc
        if source.seek(0, os.SEEK_END) != frames.encrypted_size:
            raise _invalid()
        self.position = 0
        self.cached_index = -1
        self.chunk = b""
        if not frames.size:
            self._load(0)  # Even empty plaintext must carry a final tag.

    def _load(self, index: int) -> None:
        size, nonce, aad = self.frames.frame(index)
        self.source.seek(HEADER.size + TAG + index * (CHUNK + TAG))
        try:
            self.chunk = self.frames.cipher.decrypt(nonce, self.source.read(size + TAG), aad)
        except InvalidTag as exc:
            raise _invalid() from exc
        self.cached_index = index

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.position

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        position = {os.SEEK_SET: 0, os.SEEK_CUR: self.position, os.SEEK_END: self.frames.size}[whence] + offset
        if position < 0:
            raise OSError("negative cold copy offset")
        self.position = position
        return position

    def readinto(self, buffer) -> int:
        if self.position >= self.frames.size or not len(buffer):
            return 0
        index, offset = divmod(self.position, CHUNK)
        if index != self.cached_index:
            self._load(index)
        length = min(len(buffer), len(self.chunk) - offset)
        buffer[:length] = memoryview(self.chunk)[offset:offset + length]
        self.position += length
        return length


def _require_space(path: Path, size: int) -> None:
    if shutil.disk_usage(path.parent).free < size:
        raise LifecycleError("cold_space_insufficient", "insufficient free space for the selected copy")


def encrypt_cold_copy(source: Path, output: Path, secret: bytes) -> dict[str, object]:
    with open_cold_source(source) as archive:
        identity = recovery_identity(verify_archive(archive))
        size = archive.seek(0, os.SEEK_END)
        header = HEADER.pack(MAGIC, os.urandom(16), os.urandom(7), size)
        frames = _Frames.from_header(header, secret)
        _require_space(output, frames.encrypted_size)
        archive.seek(0)
        with create_private_archive(output, independent=True) as target:
            digest = _seal(archive, target, frames)
            with io.BufferedReader(_AuthenticatedReader(target, secret)) as readback:
                if hashlib.file_digest(readback, "sha256").hexdigest() != digest:
                    raise _invalid()
            return recovery_result(identity, digest)


def read_encrypted_cold_copy(source: Path, secret: bytes, *, output: Path | None = None) -> dict[str, object]:
    with open_cold_source(source) as encrypted:
        reader = _AuthenticatedReader(encrypted, secret)
        with io.BufferedReader(reader) as plaintext:
            if output is None:
                # Hash sequentially to authenticate even bytes the ZIP reader skips.
                digest = hashlib.file_digest(plaintext, "sha256").hexdigest()
                plaintext.seek(0)
                return recovery_point(verify_archive(plaintext), digest)
            _require_space(output, reader.frames.size)
            with create_private_archive(output, independent=True) as target:
                authenticated = hashlib.sha256()
                while chunk := plaintext.read(CHUNK):
                    authenticated.update(chunk)
                    target.write(chunk)
                target.seek(0)
                digest = hashlib.file_digest(target, "sha256").hexdigest()
                if digest != authenticated.hexdigest():
                    raise LifecycleError("cold_corrupt", "decrypted archive readback differs")
                target.seek(0)
                return recovery_point(verify_archive(target), digest)
