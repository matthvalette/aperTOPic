"""Settings, read from environment variables or the project's .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # OpenParlData: public API, no key needed.
    openparldata_base_url: str = "https://api.openparldata.ch/v1"
    openparldata_site_url: str = "https://openparldata.ch"
    openparldata_timeout_s: float = 30.0

    # Apertus, served through the Keera gateway's OpenAI-compatible API.
    apertus_api_key: SecretStr | None = None
    apertus_base_url: str = "https://gateway.keera.ch/api/v1"
    apertus_model: str = "apertus-v1-5-70b"
    apertus_timeout_s: float = 60.0

    # TypeSafe Jev. Pinned to a version so tuned thresholds stay valid. jev-1.14.0 scored
    # slightly higher than jev-1.13.0 on the subject-area evaluation (F1 68.4% vs 67.1%, German).
    typesafe_api_key: SecretStr | None = None
    typesafe_model: str = "jev-1.14.0"
    typesafe_timeout_s: float = 60.0
    typesafe_max_concurrency: int = 8

    # Labelled data from files.openparldata.ch/hackapertus, and the bodies export for parliament
    # names. Relative paths are resolved against the project folder. data/ is gitignored.
    data_dir: Path = Path("data/hackapertus")
    bodies_file: Path = Path("data/exports/bodies.ndjson.gz")
    cache_dir: Path = Path(".cache")

    # How much text goes to Jev.
    max_section_chars: int = 6000
    max_state_chars: int = 16000

    @field_validator("data_dir", "bodies_file", "cache_dir")
    @classmethod
    def _project_relative(cls, value: Path) -> Path:
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
