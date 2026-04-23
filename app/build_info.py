import os
from pathlib import Path


def _read_file(path: Path) -> str | None:
    try:
        value = path.read_text(encoding='utf-8').strip()
    except OSError:
        return None
    return value or None


def get_version() -> str:
    return os.getenv('APP_VERSION') or _read_file(Path(__file__).resolve().parent.parent / 'VERSION') or 'dev'


def get_build_date() -> str:
    env = os.getenv('BUILD_DATE', '')
    if env and env != 'unknown':
        return env
    return _read_file(Path(__file__).resolve().parent.parent / 'BUILD_DATE') or 'unknown'
