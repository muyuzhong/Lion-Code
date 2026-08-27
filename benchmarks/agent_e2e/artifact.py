"""从 Git object 构建可审计的 Lion wheel。"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .models import VerifiedProvenance

ARTIFACT_BUILDER_VERSION = "git-object-wheel/v1"


class ArtifactBuildError(RuntimeError):
    """Git object、临时源码树或 wheel 构建不满足产物契约。"""


@dataclass(frozen=True, slots=True)
class CommitArtifact:
    """已从单个 Git commit 构建的 wheel 及其内存 provenance。"""

    commit_sha: str
    tree_sha: str
    wheel_path: Path
    wheel_sha256: str
    wheel_size_bytes: int
    source_tree_sha256: str
    repository_fingerprint: str
    python_version: str
    platform: str
    builder_version: str = ARTIFACT_BUILDER_VERSION

    def to_provenance(
        self,
        *,
        harbor_version: str | None = None,
        swebench_version: str | None = None,
        image_digest: str | None = None,
        dependency_fingerprint: str | None = None,
    ) -> VerifiedProvenance:
        """将内存中的产物信息收敛为现有严格 provenance 模型。"""

        return VerifiedProvenance(
            git_commit_sha=self.commit_sha,
            git_tree_sha=self.tree_sha,
            wheel_sha256=self.wheel_sha256,
            wheel_filename=self.wheel_path.name,
            wheel_size_bytes=self.wheel_size_bytes,
            source_tree_sha256=self.source_tree_sha256,
            repository_fingerprint=self.repository_fingerprint,
            python_version=self.python_version,
            platform=self.platform,
            builder_version=self.builder_version,
            harbor_version=harbor_version,
            swebench_version=swebench_version,
            image_digest=image_digest,
            dependency_fingerprint=dependency_fingerprint,
        )


class CommitArtifactBuilder:
    """只读取 Git object，不把当前 dirty worktree 复制进评测产物。"""

    def __init__(
        self,
        repository_root: str | Path,
        *,
        python_executable: str | Path = sys.executable,
        staging_root: str | Path | None = None,
        builder_version: str = ARTIFACT_BUILDER_VERSION,
    ) -> None:
        self.repository_root = Path(repository_root).resolve()
        self.python_executable = str(python_executable)
        self.staging_root = (
            Path(staging_root).resolve() if staging_root is not None else None
        )
        self.builder_version = builder_version

    def build(self, commit_sha: str, output_dir: str | Path) -> CommitArtifact:
        """导出 commit tree、构建 wheel，并只保留调用方指定的最终 wheel。"""

        resolved_commit = self._resolve_commit(commit_sha)
        tree_sha = self._git_output("rev-parse", f"{resolved_commit}^{{tree}}")
        tree_listing = self._git_bytes(
            "ls-tree",
            "-r",
            "-z",
            "--full-tree",
            resolved_commit,
        )
        source_tree_sha256 = _sha256_bytes(tree_listing)
        repository_fingerprint = self._repository_fingerprint(tree_sha)

        destination = Path(output_dir).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        staging_created = False
        if self.staging_root is not None:
            staging_created = not self.staging_root.exists()
            self.staging_root.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(
                prefix="lion-e2e-artifact-",
                dir=str(self.staging_root) if self.staging_root is not None else None,
            ) as temporary_directory:
                temporary_root = Path(temporary_directory)
                archive_path = temporary_root / "source.tar"
                source_root = temporary_root / "source"
                wheel_root = temporary_root / "wheel"
                source_root.mkdir()
                wheel_root.mkdir()
                self._git_archive(resolved_commit, archive_path)
                self._extract_archive(archive_path, source_root)
                self._build_wheel(source_root, wheel_root)
                wheels = sorted(wheel_root.glob("*.whl"))
                if len(wheels) != 1:
                    raise ArtifactBuildError(
                        f"Expected exactly one wheel, found {len(wheels)}"
                    )
                wheel_source = wheels[0]
                self._canonicalize_wheel(wheel_source)
                wheel_destination = destination / wheel_source.name
                temporary_destination = destination / f".{wheel_source.name}.tmp"
                shutil.copy2(wheel_source, temporary_destination)
                os.replace(temporary_destination, wheel_destination)
        finally:
            if (
                staging_created
                and self.staging_root is not None
                and self.staging_root.exists()
                and not any(self.staging_root.iterdir())
            ):
                self.staging_root.rmdir()

        return CommitArtifact(
            commit_sha=resolved_commit,
            tree_sha=tree_sha,
            wheel_path=wheel_destination,
            wheel_sha256=_sha256_file(wheel_destination),
            wheel_size_bytes=wheel_destination.stat().st_size,
            source_tree_sha256=source_tree_sha256,
            repository_fingerprint=repository_fingerprint,
            python_version=platform.python_version(),
            platform=sys.platform,
            builder_version=self.builder_version,
        )

    def _resolve_commit(self, commit_sha: str) -> str:
        if not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit_sha):
            raise ArtifactBuildError("commit_sha must be a hexadecimal Git SHA")
        resolved = self._git_output("rev-parse", "--verify", f"{commit_sha}^{{commit}}")
        if not re.fullmatch(r"[0-9a-f]{40}", resolved):
            raise ArtifactBuildError("Git did not return a full commit SHA")
        return resolved

    def _repository_fingerprint(self, tree_sha: str) -> str:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=self.repository_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_git_environment(),
        )
        remote = result.stdout.strip() if result.returncode == 0 else ""
        identity = remote or f"git-tree:{tree_sha}"
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def _git_archive(self, commit_sha: str, archive_path: Path) -> None:
        result = subprocess.run(
            ["git", "archive", "--format=tar", f"--output={archive_path}", commit_sha],
            cwd=self.repository_root,
            check=False,
            capture_output=True,
            env=_git_environment(),
        )
        if result.returncode != 0:
            raise ArtifactBuildError("Unable to export the requested Git commit")

    def _build_wheel(self, source_root: Path, wheel_root: Path) -> None:
        result = subprocess.run(
            [
                self.python_executable,
                "-m",
                "build",
                "--wheel",
                "--outdir",
                str(wheel_root),
            ],
            cwd=source_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        if result.returncode != 0:
            raise ArtifactBuildError("Building the commit wheel failed")

    @staticmethod
    def _canonicalize_wheel(wheel_path: Path) -> None:
        """消除构建工具写入的当前时间戳，使相同 Git tree 的 digest 稳定。"""

        temporary_path = wheel_path.with_name(f".{wheel_path.name}.normalized")
        try:
            with (
                zipfile.ZipFile(wheel_path, "r") as source,
                zipfile.ZipFile(
                    temporary_path,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                ) as destination,
            ):
                names = source.namelist()
                if len(names) != len(set(names)):
                    raise ArtifactBuildError("Wheel contains duplicate archive entries")
                for name in sorted(names):
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.create_system = 3
                    info.external_attr = source.getinfo(name).external_attr
                    destination.writestr(info, source.read(name))
            os.replace(temporary_path, wheel_path)
        except (OSError, zipfile.BadZipFile) as error:
            if temporary_path.exists():
                temporary_path.unlink()
            raise ArtifactBuildError(
                "Unable to canonicalize the commit wheel"
            ) from error

    def _git_output(self, *arguments: str) -> str:
        result = subprocess.run(
            ["git", *arguments],
            cwd=self.repository_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            env=_git_environment(),
        )
        if result.returncode != 0:
            raise ArtifactBuildError("Git could not resolve the requested object")
        return result.stdout.strip()

    def _git_bytes(self, *arguments: str) -> bytes:
        result = subprocess.run(
            ["git", *arguments],
            cwd=self.repository_root,
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            env=_git_environment(),
        )
        if result.returncode != 0:
            raise ArtifactBuildError("Git could not read the requested tree")
        return result.stdout

    @staticmethod
    def _extract_archive(archive_path: Path, source_root: Path) -> None:
        try:
            with tarfile.open(archive_path, "r") as archive:
                archive.extractall(source_root, filter="data")
        except (OSError, tarfile.TarError) as error:
            raise ArtifactBuildError(
                "Git archive contains unsafe or unreadable files"
            ) from error


def build_commit_artifact(
    repository_root: str | Path,
    commit_sha: str,
    output_dir: str | Path,
    *,
    python_executable: str | Path = sys.executable,
    staging_root: str | Path | None = None,
) -> CommitArtifact:
    """构建单个 Git commit 的 wheel；这是 CLI/runner 的薄入口。"""

    return CommitArtifactBuilder(
        repository_root,
        python_executable=python_executable,
        staging_root=staging_root,
    ).build(commit_sha, output_dir)


def _git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return environment


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "ARTIFACT_BUILDER_VERSION",
    "ArtifactBuildError",
    "CommitArtifact",
    "CommitArtifactBuilder",
    "build_commit_artifact",
]
