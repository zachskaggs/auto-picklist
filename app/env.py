import os
from pathlib import Path


def load_optional_dotenv(path: str = '.env') -> None:
    """Load a local .env file only when explicitly enabled for dev."""
    flag = (os.getenv('LOAD_DOTENV') or '').strip().lower()
    if flag not in ('1', 'true', 'yes'):
        return
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value
