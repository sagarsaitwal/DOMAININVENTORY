"""Environment-backed application configuration.

Author: Sagar Saitwal
"""

from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    cloudflare_api_token: str
    cloudflare_timeout_seconds: int
    cloudflare_retries: int
    rdap_timeout_seconds: int
    godaddy_api_key: str
    godaddy_api_secret: str
    godaddy_api_base_url: str
    godaddy_timeout_seconds: int
    godaddy_retries: int
    godaddy_max_workers: int
    output_dir: str
    log_dir: str

    @classmethod
    def from_environment(cls) -> "Settings":
        load_dotenv()
        return cls(
            cloudflare_api_token=os.getenv("CLOUDFLARE_API_TOKEN", "").strip(),
            cloudflare_timeout_seconds=int(os.getenv("CLOUDFLARE_TIMEOUT_SECONDS", "20")),
            cloudflare_retries=int(os.getenv("CLOUDFLARE_RETRIES", "3")),
            rdap_timeout_seconds=int(os.getenv("RDAP_TIMEOUT_SECONDS", "12")),
            godaddy_api_key=os.getenv("GODADDY_API_KEY", "").strip(),
            godaddy_api_secret=os.getenv("GODADDY_API_SECRET", "").strip(),
            godaddy_api_base_url=os.getenv("GODADDY_API_BASE_URL", "https://api.godaddy.com").rstrip("/"),
            godaddy_timeout_seconds=int(os.getenv("GODADDY_TIMEOUT_SECONDS", "20")),
            godaddy_retries=int(os.getenv("GODADDY_RETRIES", "3")),
            godaddy_max_workers=int(os.getenv("GODADDY_MAX_WORKERS", "2")),
            output_dir=os.getenv("OUTPUT_DIR", "output"),
            log_dir=os.getenv("LOG_DIR", "logs"),
        )
