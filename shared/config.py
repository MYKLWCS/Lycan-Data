from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://lycan:lycan@localhost:5432/lycan"
    database_url_sync: str = "postgresql://lycan:lycan@localhost:5432/lycan"

    # Dragonfly / Redis
    dragonfly_url: str = "redis://localhost:6379/0"

    # MeiliSearch
    meili_url: str = "http://localhost:7700"
    meili_master_key: str = "changeme"

    # Tor
    tor_control_password: str = "changeme"
    tor_enabled: bool = True
    proxy_override: str = ""

    # Tor instance endpoints
    tor1_socks: str = "socks5://127.0.0.1:9050"
    tor1_control_port: int = 9051
    tor2_socks: str = "socks5://127.0.0.1:9052"
    tor2_control_port: int = 9053
    tor3_socks: str = "socks5://127.0.0.1:9054"
    tor3_control_port: int = 9055

    # Module kill switches
    enable_instagram: bool = True
    enable_linkedin: bool = True
    enable_twitter: bool = True
    enable_facebook: bool = True
    enable_tiktok: bool = True
    enable_telegram: bool = True
    enable_darkweb: bool = True
    enable_burner_check: bool = True
    enable_credit_risk: bool = True
    enable_wealth: bool = True
    enable_criminal_signals: bool = True
    enable_crypto_trace: bool = True
    enable_ubo_discovery: bool = True
    enable_company_intel_crawl: bool = True

    # Budget
    daily_api_budget_usd: float = 0.0

    # App
    secret_key: str = "changeme-32-chars-minimum-please"
    debug: bool = False
    log_level: str = "INFO"

    # Freshness thresholds (hours)
    freshness_threshold: float = 0.40
    rescrape_on_staleness: bool = True


settings = Settings()
