from pathlib import Path
from shutil import rmtree
from uuid import UUID

from app.core.config import Settings


class JobArtifactRemovalError(Exception):
    pass


def _job_id(job_id: str) -> str:
    try:
        return str(UUID(job_id))
    except (AttributeError, TypeError, ValueError) as error:
        raise JobArtifactRemovalError("Job ID is invalid.") from error


def _remove_file(path: Path) -> None:
    if path.is_symlink():
        raise JobArtifactRemovalError("Job file path is invalid.")
    if not path.exists():
        return
    if not path.is_file():
        raise JobArtifactRemovalError("Job file path is invalid.")
    path.unlink()


def _remove_directory(path: Path) -> None:
    if path.is_symlink():
        raise JobArtifactRemovalError("Job directory path is invalid.")
    if not path.exists():
        return
    if not path.is_dir():
        raise JobArtifactRemovalError("Job directory path is invalid.")
    rmtree(path)


def remove_job_artifacts(settings: Settings, job_id: str) -> None:
    normalized_job_id = _job_id(job_id)
    storage_root = settings.storage_root.resolve()
    artifacts: tuple[tuple[Path, bool], ...] = (
        (storage_root / "originals" / f"{normalized_job_id}.pdf", False),
        (storage_root / "previews" / normalized_job_id, True),
        (storage_root / "results" / f"{normalized_job_id}.pdf", False),
        (
            storage_root / "temporary" / f"{normalized_job_id}.translation",
            True,
        ),
    )

    try:
        for artifact, is_directory in artifacts:
            resolved = artifact.resolve()
            if resolved.parent != artifact.parent.resolve():
                raise JobArtifactRemovalError("Job artifact path is invalid.")
            if is_directory:
                _remove_directory(artifact)
            else:
                _remove_file(artifact)
    except JobArtifactRemovalError:
        raise
    except OSError as error:
        raise JobArtifactRemovalError("Job artifacts could not be removed.") from error
