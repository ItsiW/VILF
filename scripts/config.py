"""Settings read from the environment (and <repo root>/.env).

Attribute names are the env names lowercased with the VILF_ prefix stripped.
"""

import functools
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./vilf.db"
    media_storage: str = "./.media"
    site_storage: str = "./.site"
    site_url: str = "https://vilf.org"
    google_cloud_project: str | None = None
    url_map: str | None = None
    google_places_api_key: str | None = None
    google_maps_embed_api_key: str | None = None
    admin_email: str | None = None
    dev_user: str = "dev@localhost"
    indexnow: bool = False
    port: int = 8000

    @classmethod
    def from_env(cls, env=None) -> "Settings":
        """Build settings from `env` (default os.environ) after loading <repo root>/.env.

        Empty strings count as unset. Explicit env values are never overridden by .env.
        """
        load_dotenv(REPO_ROOT / ".env", override=False)
        if env is None:
            env = os.environ

        def get(name, default=None):
            value = env.get(name)
            if value is None or value.strip() == "":
                return default
            return value.strip()

        return cls(
            database_url=get("DATABASE_URL", cls.database_url),
            media_storage=get("VILF_MEDIA_STORAGE", cls.media_storage),
            site_storage=get("VILF_SITE_STORAGE", cls.site_storage),
            site_url=get("VILF_SITE_URL", cls.site_url),
            google_cloud_project=get("GOOGLE_CLOUD_PROJECT"),
            url_map=get("VILF_URL_MAP"),
            google_places_api_key=get("GOOGLE_PLACES_API_KEY"),
            google_maps_embed_api_key=get("GOOGLE_MAPS_EMBED_API_KEY"),
            admin_email=get("VILF_ADMIN_EMAIL"),
            dev_user=get("VILF_DEV_USER", cls.dev_user),
            indexnow=get("VILF_INDEXNOW", "0").lower() in _TRUE,
            port=int(get("PORT", str(cls.port))),
        )


@functools.lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings.from_env()
