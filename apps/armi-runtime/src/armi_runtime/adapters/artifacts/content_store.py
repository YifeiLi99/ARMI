"""Windows-local content-addressed storage with verified reads."""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import os
import re
import stat
from collections.abc import AsyncIterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Final, Self
from uuid import UUID, uuid7

from armi_kernel.application import (
    ArtifactId,
    ArtifactPolicy,
    ArtifactRef,
    ArtifactViolation,
    PublishedArtifact,
    StagedArtifact,
)
from armi_kernel.contracts import Digest

_OBJECT_NAME = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SHARD_NAME = re.compile(r"^[0-9a-f]{2}$", re.ASCII)
_STAGE_NAME = re.compile(r"^stage-([0-9a-f]{32})\.tmp$", re.ASCII)
_FILE_ATTRIBUTE_DIRECTORY: Final = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT: Final = 0x00000400
_GENERIC_READ: Final = 0x80000000
_FILE_SHARE_READ: Final = 0x00000001
_OPEN_EXISTING: Final = 3
_FILE_FLAG_OPEN_REPARSE_POINT: Final = 0x00200000
_FILE_FLAG_SEQUENTIAL_SCAN: Final = 0x08000000


@dataclass(frozen=True, slots=True, order=True)
class StorageFinding:
    category: str
    artifact_id: str | None
    content_digest: str | None


@dataclass(frozen=True, slots=True)
class StorageCleanupResult:
    removed_counts: tuple[tuple[str, int], ...]
    removed_bytes: int
    remaining: tuple[StorageFinding, ...]


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = (
        ("file_attributes", ctypes.c_uint32),
        ("creation_time_low", ctypes.c_uint32),
        ("creation_time_high", ctypes.c_uint32),
        ("last_access_time_low", ctypes.c_uint32),
        ("last_access_time_high", ctypes.c_uint32),
        ("last_write_time_low", ctypes.c_uint32),
        ("last_write_time_high", ctypes.c_uint32),
        ("volume_serial_number", ctypes.c_uint32),
        ("file_size_high", ctypes.c_uint32),
        ("file_size_low", ctypes.c_uint32),
        ("number_of_links", ctypes.c_uint32),
        ("file_index_high", ctypes.c_uint32),
        ("file_index_low", ctypes.c_uint32),
    )


class VerifiedFileStream:
    __slots__ = ("_file",)

    def __init__(self, file_value: BinaryIO) -> None:
        self._file: BinaryIO | None = file_value

    async def read(self, size: int = -1) -> bytes:
        if type(size) is not int or size < -1:
            raise ArtifactViolation("ART-STATE")
        if self._file is None:
            raise ArtifactViolation("ART-STATE")
        return await asyncio.to_thread(self._file.read, size)

    async def close(self) -> None:
        if self._file is not None:
            file_value = self._file
            self._file = None
            await asyncio.to_thread(file_value.close)

    async def __aenter__(self) -> Self:
        if self._file is None:
            raise ArtifactViolation("ART-STATE")
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        await self.close()
        return False


class ContentAddressedArtifactStore:
    """Store immutable bytes below one explicit artifact root."""

    __slots__ = (
        "_max_object_bytes",
        "_objects",
        "_quarantine",
        "_root",
        "_staged",
        "_staging",
    )

    def __init__(self, artifact_root: object, *, max_object_bytes: int) -> None:
        if (
            not isinstance(artifact_root, Path)
            or not artifact_root.is_absolute()
            or type(max_object_bytes) is not int
            or max_object_bytes <= 0
        ):
            raise ArtifactViolation("ART-DECLARATION")
        self._root = artifact_root
        self._objects = artifact_root / "objects"
        self._staging = artifact_root / "staging"
        self._quarantine = artifact_root / "quarantine"
        self._max_object_bytes = max_object_bytes
        self._staged: dict[ArtifactId, Path] = {}

    async def prepare(self) -> None:
        await asyncio.to_thread(self._prepare_sync)

    async def stage(
        self,
        source: AsyncIterable[bytes],
        policy: ArtifactPolicy,
    ) -> StagedArtifact:
        if type(policy) is not ArtifactPolicy or not hasattr(source, "__aiter__"):
            raise ArtifactViolation("ART-DECLARATION")
        await self.prepare()
        stage_id = ArtifactId(uuid7())
        stage_path = self._staging / f"stage-{stage_id.value.hex}.tmp"
        digest = hashlib.sha256()
        byte_size = 0
        file_value: BinaryIO | None = None
        try:
            file_value = await asyncio.to_thread(stage_path.open, "xb")
            async for chunk in source:
                if type(chunk) is not bytes or not chunk:
                    raise ArtifactViolation("ART-SOURCE")
                byte_size += len(chunk)
                if byte_size > self._max_object_bytes:
                    raise ArtifactViolation("ART-SIZE-LIMIT")
                digest.update(chunk)
                await asyncio.to_thread(file_value.write, chunk)
            if byte_size == 0:
                raise ArtifactViolation("ART-SIZE-LIMIT")
            await asyncio.to_thread(file_value.flush)
            await asyncio.to_thread(os.fsync, file_value.fileno())
            await asyncio.to_thread(file_value.close)
            file_value = None
        except BaseException as error:
            if file_value is not None:
                with suppress(OSError):
                    await asyncio.to_thread(file_value.close)
            with suppress(OSError):
                await asyncio.to_thread(stage_path.unlink, missing_ok=True)
            if isinstance(error, asyncio.CancelledError):
                raise
            if isinstance(error, ArtifactViolation):
                raise
            if isinstance(error, (OSError, TypeError)):
                raise ArtifactViolation("ART-STAGING-IO") from None
            if isinstance(error, Exception):
                raise ArtifactViolation("ART-SOURCE") from None
            raise
        staged = StagedArtifact(
            stage_id=stage_id,
            content_digest=Digest(f"sha256:{digest.hexdigest()}"),
            byte_size=byte_size,
            policy=policy,
        )
        self._staged[stage_id] = stage_path
        return staged

    async def publish(self, staged: StagedArtifact) -> PublishedArtifact:
        if type(staged) is not StagedArtifact:
            raise ArtifactViolation("ART-DECLARATION")
        stage_path = self._staged.get(staged.stage_id)
        if stage_path is None:
            raise ArtifactViolation("ART-STATE")
        digest_hex = staged.content_digest.value.removeprefix("sha256:")
        target = self._object_path(digest_hex)
        try:
            file_value = await asyncio.to_thread(
                self._open_verified_sync,
                stage_path,
                staged.content_digest,
                staged.byte_size,
                self._staging,
            )
            file_value.close()
            await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(self._assert_safe_tree)
            await asyncio.to_thread(self._assert_safe_directory_chain, target.parent)
            if stage_path.stat().st_dev != target.parent.stat().st_dev:
                raise ArtifactViolation("ART-PATH-UNSAFE")
            try:
                await asyncio.to_thread(os.rename, stage_path, target)
            except OSError:
                if not target.exists():
                    raise ArtifactViolation("ART-PUBLISH-IO") from None
                try:
                    file_value = await asyncio.to_thread(
                        self._open_verified_sync,
                        target,
                        staged.content_digest,
                        staged.byte_size,
                        self._objects,
                    )
                    file_value.close()
                except ArtifactViolation:
                    quarantine = (
                        self._quarantine / f"{digest_hex}.{uuid7().hex}.corrupt"
                    )
                    try:
                        await asyncio.to_thread(os.rename, target, quarantine)
                    except OSError:
                        raise ArtifactViolation("ART-DIGEST-CONFLICT") from None
                    await asyncio.to_thread(stage_path.unlink, missing_ok=True)
                    raise ArtifactViolation("ART-DIGEST-CONFLICT") from None
                await asyncio.to_thread(stage_path.unlink, missing_ok=True)
        except ArtifactViolation:
            self._staged.pop(staged.stage_id, None)
            raise
        except OSError:
            self._staged.pop(staged.stage_id, None)
            raise ArtifactViolation("ART-PUBLISH-IO") from None
        self._staged.pop(staged.stage_id, None)
        return PublishedArtifact(
            stage_id=staged.stage_id,
            content_digest=staged.content_digest,
            byte_size=staged.byte_size,
            policy=staged.policy,
        )

    async def discard(self, staged: StagedArtifact) -> None:
        if type(staged) is not StagedArtifact:
            raise ArtifactViolation("ART-DECLARATION")
        path = self._staged.pop(staged.stage_id, None)
        if path is not None:
            try:
                await asyncio.to_thread(path.unlink, missing_ok=True)
            except OSError:
                raise ArtifactViolation("ART-STAGING-IO") from None

    async def open_verified(self, ref: ArtifactRef) -> VerifiedFileStream:
        if type(ref) is not ArtifactRef:
            raise ArtifactViolation("ART-DECLARATION")
        digest_hex = ref.content_digest.value.removeprefix("sha256:")
        path = self._object_path(digest_hex)
        try:
            file_value = await asyncio.to_thread(
                self._open_verified_sync,
                path,
                ref.content_digest,
                ref.byte_size,
                self._objects,
            )
        except FileNotFoundError:
            raise ArtifactViolation("ART-MISSING") from None
        except ArtifactViolation as error:
            if error.code == "ART-CORRUPT":
                await asyncio.to_thread(self._quarantine_corrupt_sync, path, digest_hex)
            raise
        except OSError:
            raise ArtifactViolation("ART-PATH-UNSAFE") from None
        return VerifiedFileStream(file_value)

    async def delete_verified(self, ref: ArtifactRef) -> bool:
        """Delete one exact registered object after revalidating its identity."""

        if type(ref) is not ArtifactRef:
            raise ArtifactViolation("ART-DECLARATION")
        try:
            return await asyncio.to_thread(self._delete_verified_sync, ref)
        except FileNotFoundError:
            return False
        except ArtifactViolation:
            raise
        except OSError:
            raise ArtifactViolation("ART-DELETE-IO") from None

    async def scan(
        self,
        *,
        cutoff: datetime,
        registered: dict[str, ArtifactRef],
    ) -> tuple[StorageFinding, ...]:
        if (
            type(cutoff) is not datetime
            or cutoff.tzinfo is None
            or cutoff.utcoffset() != UTC.utcoffset(cutoff)
        ):
            raise ArtifactViolation("ART-ORPHAN-SCAN")
        try:
            return await asyncio.to_thread(
                self._scan_sync,
                cutoff,
                registered,
            )
        except ArtifactViolation:
            raise
        except OSError:
            raise ArtifactViolation("ART-ORPHAN-SCAN") from None

    async def cleanup(
        self,
        *,
        cutoff: datetime,
        registered: dict[str, ArtifactRef],
    ) -> StorageCleanupResult:
        """Delete only revalidated stale staging and unregistered objects."""

        if (
            type(cutoff) is not datetime
            or cutoff.tzinfo is None
            or cutoff.utcoffset() != UTC.utcoffset(cutoff)
        ):
            raise ArtifactViolation("ART-ORPHAN-CLEANUP")
        try:
            return await asyncio.to_thread(
                self._cleanup_sync,
                cutoff,
                registered,
            )
        except ArtifactViolation:
            raise
        except OSError:
            raise ArtifactViolation("ART-ORPHAN-CLEANUP") from None

    def _prepare_sync(self) -> None:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            self._objects.mkdir(exist_ok=True)
            self._staging.mkdir(exist_ok=True)
            self._quarantine.mkdir(exist_ok=True)
            self._assert_safe_tree()
            if self._objects.stat().st_dev != self._staging.stat().st_dev:
                raise ArtifactViolation("ART-PATH-UNSAFE")
        except ArtifactViolation:
            raise
        except OSError:
            raise ArtifactViolation("ART-STAGING-IO") from None

    def _delete_verified_sync(self, ref: ArtifactRef) -> bool:
        self._prepare_sync()
        digest_hex = ref.content_digest.value.removeprefix("sha256:")
        path = self._object_path(digest_hex)
        file_value = self._open_verified_sync(
            path,
            ref.content_digest,
            ref.byte_size,
            self._objects,
        )
        try:
            opened = os.fstat(file_value.fileno())
        finally:
            file_value.close()
        current = path.lstat()
        if (
            current.st_dev != opened.st_dev
            or current.st_ino != opened.st_ino
            or not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or path.is_symlink()
            or getattr(current, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ArtifactViolation("ART-PATH-UNSAFE")
        path.unlink()
        return True

    def _assert_safe_tree(self) -> None:
        for path in (
            self._root,
            self._objects,
            self._staging,
            self._quarantine,
        ):
            metadata = path.lstat()
            attributes = getattr(metadata, "st_file_attributes", 0)
            if (
                path.is_symlink()
                or not path.is_dir()
                or attributes & _FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise ArtifactViolation("ART-PATH-UNSAFE")
        if self._root.resolve(strict=True) != self._root:
            raise ArtifactViolation("ART-PATH-UNSAFE")

    def _object_path(self, digest_hex: str) -> Path:
        if _OBJECT_NAME.fullmatch(digest_hex) is None:
            raise ArtifactViolation("ART-DECLARATION")
        return self._objects / "sha256" / digest_hex[:2] / digest_hex[2:4] / digest_hex

    def _assert_safe_directory_chain(self, leaf: Path) -> None:
        root = self._objects.resolve(strict=True)
        leaf.resolve(strict=True).relative_to(root)
        current = leaf
        while current != self._objects:
            metadata = current.lstat()
            if (
                not current.is_dir()
                or current.is_symlink()
                or getattr(metadata, "st_file_attributes", 0)
                & _FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise ArtifactViolation("ART-PATH-UNSAFE")
            current = current.parent

    def _open_verified_sync(
        self,
        path: Path,
        digest: Digest,
        byte_size: int,
        allowed_root: Path,
    ) -> BinaryIO:
        file_value = _open_windows_verified_handle(path, allowed_root)
        try:
            metadata = os.fstat(file_value.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_size != byte_size
            ):
                raise ArtifactViolation("ART-CORRUPT")
            hasher = hashlib.sha256()
            while chunk := file_value.read(1024 * 1024):
                hasher.update(chunk)
            calculated = hasher.hexdigest()
            if f"sha256:{calculated}" != digest.value:
                raise ArtifactViolation("ART-CORRUPT")
            file_value.seek(0)
            return file_value
        except BaseException:
            file_value.close()
            raise

    def _quarantine_corrupt_sync(self, path: Path, digest_hex: str) -> None:
        if not path.exists():
            return
        target = self._quarantine / f"{digest_hex}.{uuid7().hex}.corrupt"
        try:
            os.rename(path, target)
        except OSError:
            raise ArtifactViolation("ART-CORRUPT") from None

    def _scan_sync(
        self,
        cutoff: datetime,
        registered: dict[str, ArtifactRef],
    ) -> tuple[StorageFinding, ...]:
        self._assert_safe_tree()
        findings: list[StorageFinding] = []
        seen: set[str] = set()
        cutoff_timestamp = cutoff.timestamp()
        for path in sorted(self._staging.iterdir(), key=lambda item: item.name):
            match = _STAGE_NAME.fullmatch(path.name)
            if match is None or not _safe_regular(path):
                findings.append(StorageFinding("invalid_entry", None, None))
            elif path.stat().st_mtime <= cutoff_timestamp:
                findings.append(
                    StorageFinding(
                        "stale_staging",
                        str(UUID(hex=match.group(1))),
                        None,
                    )
                )
        sha_root = self._objects / "sha256"
        if sha_root.exists():
            findings.extend(
                self._scan_object_tree(
                    sha_root,
                    cutoff_timestamp=cutoff_timestamp,
                    registered=registered,
                    seen=seen,
                )
            )
        for digest, ref in sorted(registered.items()):
            if digest not in seen:
                findings.append(
                    StorageFinding(
                        "missing_registered",
                        str(ref.artifact_id),
                        digest,
                    )
                )
        return tuple(sorted(findings))

    def _cleanup_sync(
        self,
        cutoff: datetime,
        registered: dict[str, ArtifactRef],
    ) -> StorageCleanupResult:
        findings = self._scan_sync(cutoff, registered)
        removed: dict[str, int] = {}
        removed_bytes = 0
        cutoff_timestamp = cutoff.timestamp()
        for finding in findings:
            path: Path | None = None
            if finding.category == "stale_staging" and finding.artifact_id is not None:
                stage_id = UUID(finding.artifact_id)
                path = self._staging / f"stage-{stage_id.hex}.tmp"
            elif (
                finding.category == "unregistered_object"
                and finding.content_digest is not None
                and finding.content_digest not in registered
            ):
                path = self._object_path(finding.content_digest.removeprefix("sha256:"))
            if path is None:
                continue
            metadata = path.lstat()
            if metadata.st_mtime > cutoff_timestamp or not _safe_regular(path):
                raise ArtifactViolation("ART-ORPHAN-CLEANUP")
            allowed_root = (
                self._staging if finding.category == "stale_staging" else self._objects
            )
            try:
                path.resolve(strict=True).relative_to(allowed_root.resolve(strict=True))
            except ValueError, OSError:
                raise ArtifactViolation("ART-ORPHAN-CLEANUP") from None
            byte_size = metadata.st_size
            path.unlink()
            removed[finding.category] = removed.get(finding.category, 0) + 1
            removed_bytes += byte_size
        remaining = self._scan_sync(cutoff, registered)
        return StorageCleanupResult(
            removed_counts=tuple(sorted(removed.items())),
            removed_bytes=removed_bytes,
            remaining=remaining,
        )

    def _scan_object_tree(
        self,
        sha_root: Path,
        *,
        cutoff_timestamp: float,
        registered: dict[str, ArtifactRef],
        seen: set[str],
    ) -> list[StorageFinding]:
        findings: list[StorageFinding] = []
        if not _safe_directory(sha_root):
            return [StorageFinding("invalid_entry", None, None)]
        pending = [(sha_root, 0)]
        while pending:
            directory, depth = pending.pop()
            for path in sorted(directory.iterdir(), key=lambda item: item.name):
                if path.is_dir():
                    if (
                        depth >= 2
                        or _SHARD_NAME.fullmatch(path.name) is None
                        or not _safe_directory(path)
                    ):
                        findings.append(StorageFinding("invalid_entry", None, None))
                    else:
                        pending.append((path, depth + 1))
                    continue
                digest_hex = path.name
                relative = path.relative_to(sha_root)
                valid_location = (
                    depth == 2
                    and len(relative.parts) == 3
                    and relative.parts[0] == digest_hex[:2]
                    and relative.parts[1] == digest_hex[2:4]
                    and _OBJECT_NAME.fullmatch(digest_hex) is not None
                )
                if not valid_location or not _safe_regular(path):
                    findings.append(StorageFinding("invalid_entry", None, None))
                    continue
                digest = f"sha256:{digest_hex}"
                seen.add(digest)
                ref = registered.get(digest)
                if ref is None:
                    if path.stat().st_mtime <= cutoff_timestamp:
                        findings.append(
                            StorageFinding("unregistered_object", None, digest)
                        )
                    continue
                try:
                    file_value = self._open_verified_sync(
                        path,
                        ref.content_digest,
                        ref.byte_size,
                        self._objects,
                    )
                    file_value.close()
                except ArtifactViolation, FileNotFoundError:
                    findings.append(
                        StorageFinding(
                            "corrupt_registered", str(ref.artifact_id), digest
                        )
                    )
        return findings


def _safe_regular(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(metadata.st_mode)
        and not path.is_symlink()
        and metadata.st_nlink == 1
        and not (
            getattr(metadata, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
        )
    )


def _safe_directory(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISDIR(metadata.st_mode)
        and not path.is_symlink()
        and not (
            getattr(metadata, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
        )
    )


def _open_windows_verified_handle(path: Path, root: Path) -> BinaryIO:
    if os.name != "nt":
        raise ArtifactViolation("ART-PATH-UNSAFE")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    )
    create_file.restype = ctypes.c_void_p
    handle = create_file(
        str(path),
        _GENERIC_READ,
        _FILE_SHARE_READ,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_SEQUENTIAL_SCAN,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle in (None, invalid_handle):
        error = ctypes.get_last_error()
        if error in (2, 3):
            raise FileNotFoundError
        raise ArtifactViolation("ART-PATH-UNSAFE")
    try:
        information = _ByHandleFileInformation()
        if not kernel32.GetFileInformationByHandle(
            ctypes.c_void_p(handle),
            ctypes.byref(information),
        ):
            raise ArtifactViolation("ART-PATH-UNSAFE")
        if (
            information.file_attributes
            & (_FILE_ATTRIBUTE_DIRECTORY | _FILE_ATTRIBUTE_REPARSE_POINT)
            or information.number_of_links != 1
        ):
            raise ArtifactViolation("ART-PATH-UNSAFE")
        buffer = ctypes.create_unicode_buffer(32_768)
        length = kernel32.GetFinalPathNameByHandleW(
            ctypes.c_void_p(handle),
            buffer,
            len(buffer),
            0,
        )
        if length == 0 or length >= len(buffer):
            raise ArtifactViolation("ART-PATH-UNSAFE")
        final_name = buffer.value.removeprefix("\\\\?\\")
        final_path = Path(final_name)
        final_path.relative_to(root.resolve(strict=True))
        import msvcrt

        descriptor = msvcrt.open_osfhandle(
            int(handle),
            os.O_RDONLY | os.O_BINARY,
        )
        handle = None
        return os.fdopen(descriptor, "rb", closefd=True)
    except ValueError:
        raise ArtifactViolation("ART-PATH-UNSAFE") from None
    finally:
        if handle not in (None, invalid_handle):
            kernel32.CloseHandle(ctypes.c_void_p(handle))


__all__ = (
    "ContentAddressedArtifactStore",
    "StorageCleanupResult",
    "StorageFinding",
)
