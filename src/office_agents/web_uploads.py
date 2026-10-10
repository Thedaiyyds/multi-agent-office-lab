"""Freeze and validate bounded web inputs before admitting a model-backed run."""

from collections.abc import Iterable
from pathlib import Path
from tempfile import TemporaryDirectory

from office_agents.schemas import DataIssue
from office_agents.tools.data_io import MAX_FILE_BYTES, SOURCE_IDS, _read_bytes, validate_data
from office_agents.web_schemas import SAMPLE_ROOT, PreparedInput, UploadBlob

_FILE_NAMES = ("projects.csv", "achievements.csv", "issues.txt")
_SAFE_MESSAGE = "输入文件校验失败，请按提示检查三个必需文件。"


class WebInputError(ValueError):
    """Only fixed, safe messages and structured validation issues reach the UI."""

    def __init__(self, issues: Iterable[DataIssue]):
        self.issues = tuple(issues)
        super().__init__(_SAFE_MESSAGE)


def _problem(code: str, message: str, source_id: str | None = None) -> WebInputError:
    return WebInputError(
        (DataIssue(severity="error", code=code, message=message, source_id=source_id),)
    )


def _freeze(files: Iterable[UploadBlob]) -> tuple[UploadBlob, ...]:
    """Consume at most four entries; never retain untrusted names in error messages."""
    accepted: dict[str, UploadBlob] = {}
    try:
        for index, blob in enumerate(files):
            if index >= len(_FILE_NAMES):
                raise _problem("too_many_files", "Only the three required files are accepted.")
            if not isinstance(blob, UploadBlob):
                raise _problem(
                    "invalid_upload", "Each uploaded file must contain a name and bytes."
                )
            if type(blob.name) is not str or blob.name not in SOURCE_IDS:
                raise _problem("unknown_source", "Filename must match the fixed file whitelist.")
            if blob.name in accepted:
                raise _problem("duplicate_file", "Required file was uploaded twice.", blob.name)
            if type(blob.content) is not bytes:
                raise _problem("invalid_bytes", "File content must be immutable bytes.", blob.name)
            if len(blob.content) > MAX_FILE_BYTES:
                raise _problem("file_too_large", "Source exceeds the 2 MiB limit.", blob.name)
            accepted[blob.name] = UploadBlob(blob.name, blob.content)
    except WebInputError:
        raise
    except Exception:
        raise _problem("invalid_upload", "Uploaded files cannot be read.") from None
    missing = [name for name in _FILE_NAMES if name not in accepted]
    if missing:
        raise WebInputError(
            DataIssue(
                severity="error",
                code="missing_file",
                message="Required source file is missing.",
                source_id=name,
            )
            for name in missing
        )
    return tuple(accepted[name] for name in _FILE_NAMES)


def _write_files(files: tuple[UploadBlob, ...], directory: Path) -> None:
    """Only called with frozen whitelist values; refuse existing files or symlinks."""
    created: list[Path] = []
    try:
        if directory.is_symlink() or not directory.is_dir():
            raise OSError("Invalid isolated destination")
        for blob in files:
            path = directory / blob.name
            with path.open("xb") as stream:
                created.append(path)
                stream.write(blob.content)
    except (OSError, ValueError, TypeError):
        for path in created:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise _problem("input_storage_failed", "Input files cannot be stored safely.") from None


def _validate(files: tuple[UploadBlob, ...]) -> None:
    try:
        with TemporaryDirectory(prefix="office-upload-") as temporary:
            _write_files(files, Path(temporary))
            dataset = validate_data(temporary)
            if any(issue.severity == "error" for issue in dataset.data_issues):
                raise WebInputError(dataset.data_issues)
    except WebInputError:
        raise
    except Exception:
        raise _problem("input_validation_failed", "Input files cannot be validated.") from None


def prepare_input(
    files: Iterable[UploadBlob] = (),
    *,
    use_samples: bool = False,
    sample_dir: str | Path = SAMPLE_ROOT,
) -> PreparedInput:
    """Freeze all three inputs, validate them offline, and clear temporary copies."""
    if type(use_samples) is not bool:
        raise _problem("invalid_input_mode", "Choose samples or uploaded files explicitly.")
    if use_samples:
        try:
            marker = object()
            if next(iter(files), marker) is not marker:
                raise _problem("mixed_input_mode", "Samples and uploads cannot be combined.")
        except WebInputError:
            raise
        except Exception:
            raise _problem("invalid_upload", "Uploaded files cannot be read.") from None
        sample_files = []
        for name in _FILE_NAMES:
            payload, problem = _read_bytes(sample_dir, name)
            if problem:
                raise WebInputError((problem,))
            sample_files.append(UploadBlob(name, payload))
        frozen = _freeze(sample_files)
    else:
        frozen = _freeze(files)
    _validate(frozen)
    return PreparedInput(frozen, "simulated" if use_samples else "provided")


def validate_prepared(prepared: PreparedInput) -> PreparedInput:
    """Revalidate manually constructed contracts at the background-run boundary."""
    if (
        not isinstance(prepared, PreparedInput)
        or type(prepared.data_origin) is not str
        or prepared.data_origin not in ("provided", "simulated")
    ):
        raise _problem("invalid_prepared_input", "Prepared input has an invalid source mode.")
    files = _freeze(prepared.files)
    _validate(files)
    return PreparedInput(files, prepared.data_origin)


def write_prepared(prepared: PreparedInput, directory: str | Path) -> None:
    """Validate again, then write fixed names into an existing isolated directory."""
    validated = validate_prepared(prepared)
    try:
        target = Path(directory)
    except (ValueError, TypeError):
        raise _problem("input_storage_failed", "Input files cannot be stored safely.") from None
    _write_files(validated.files, target)
