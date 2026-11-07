"""Settings, read from environment variables (and an optional .env file).

Everything that you might want to change without touching code lives here.
"""

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# US dollars per million tokens (input, output). Used for the cost ledger and the budget guard.
# Update when Anthropic changes prices: https://www.anthropic.com/pricing
PRICES_PER_MTOK = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}


def load_dotenv(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines, # comments. Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    site_dir: Path
    sources_dir: Path
    site_url: str
    monthly_budget_usd: float
    extract_model: str
    analyze_model: str
    max_extract_per_run: int
    max_analyses_per_day: int
    max_new_items_per_source: int
    user_agent: str

    @property
    def db_path(self) -> Path:
        return self.data_dir / "parallax.db"

    @property
    def briefs_dir(self) -> Path:
        return self.data_dir / "briefs"


def _path(name: str, default: str) -> Path:
    p = Path(os.environ.get(name, default))
    return p if p.is_absolute() else PROJECT_ROOT / p


def get_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    env = os.environ.get
    return Settings(
        data_dir=_path("PARALLAX_DATA_DIR", "data"),
        site_dir=_path("PARALLAX_SITE_DIR", "site"),
        sources_dir=_path("PARALLAX_SOURCES_DIR", "sources"),
        site_url=env("PARALLAX_SITE_URL", "http://localhost:8000").rstrip("/"),
        monthly_budget_usd=float(env("PARALLAX_MONTHLY_BUDGET_USD", "40")),
        extract_model=env("PARALLAX_EXTRACT_MODEL", "claude-haiku-5-5"),
        analyze_model=env("PARALLAX_ANALYZE_MODEL", "claude-sonnet-5-5"),
        max_extract_per_run=int(env("PARALLAX_MAX_EXTRACT_PER_RUN", "300")),
        max_analyses_per_day=int(env("PARALLAX_MAX_ANALYSES_PER_DAY", "12")),
        max_new_items_per_source=int(env("PARALLAX_MAX_NEW_ITEMS_PER_SOURCE", "15")),
        user_agent=env(
            "PARALLAX_USER_AGENT",
            "Mozilla/5.0 (compatible; ParallaxBot/0.1; research; +https://github.com/VGBonds/parallax)",
        ),
    )
