from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def _resolve_legacy_aliases(self) -> "Settings":
        import os

        # Only use DRAGONFLY_URL if CACHE_URL wasn't explicitly set via env
        if self.dragonfly_url and not os.environ.get("CACHE_URL"):
            self.cache_url = self.dragonfly_url
        return self

    # Database
    database_url: str = "postgresql+asyncpg://lycan:lycan@postgres:5432/lycan"
    database_url_sync: str = "postgresql://lycan:lycan@postgres:5432/lycan"

    # Cache (Garnet / Redis-compatible)
    cache_url: str = "redis://garnet:6379/0"
    dragonfly_url: str = ""  # legacy alias — use CACHE_URL instead

    # Typesense (replaced MeiliSearch for licensing compliance)
    typesense_url: str = "http://typesense:8108"

    # FlareSolverr
    flaresolverr_url: str = "http://flaresolverr:8191/v1"

    # SpiderFoot
    spiderfoot_url: str = ""
    typesense_api_key: str = "changeme"

    # CORS origins are browser-side — localhost is correct even in Docker
    # because users access the app from their browser at localhost
    cors_origins: str = "http://localhost:3000,http://localhost:8000"

    # Tor
    tor_control_password: str = "changeme"
    tor_enabled: bool = True
    proxy_override: str = ""

    # Tor instance endpoints (Docker service names as defaults)
    tor1_socks: str = "socks5://tor-1:9050"
    tor1_control_host: str = "tor-1"
    tor1_control_port: int = 9051
    tor2_socks: str = "socks5://tor-2:9050"
    tor2_control_host: str = "tor-2"
    tor2_control_port: int = 9053
    tor3_socks: str = "socks5://tor-3:9050"
    tor3_control_host: str = "tor-3"
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

    # Third-party API overrides (optional — crawlers fall back to public sources without these)
    attom_api_key: str = ""  # ATTOM property data API override
    opensanctions_api_key: str = ""  # OpenSanctions API override
    opencorporates_api_key: str = ""  # OpenCorporates API override
    marinetraffic_api_key: str = ""  # MarineTraffic AIS API override

    # Budget
    daily_api_budget_usd: float = 0.0

    # App
    secret_key: str = "changeme-32-chars-minimum-please"
    debug: bool = False
    log_level: str = "INFO"

    # API Authentication — comma-separated list of valid API keys
    api_keys: str = ""  # e.g. "key1,key2,key3"
    api_auth_enabled: bool = True  # set False to disable auth (dev only)

    # Freshness thresholds (hours)
    freshness_threshold: float = 0.40
    rescrape_on_staleness: bool = True

    # Proxy pool — residential (highest anonymity)
    residential_proxies: str = ""  # comma-separated: "http://user:pass@host:port,..."
    # Proxy pool — datacenter
    datacenter_proxies: str = ""  # comma-separated

    # Per-crawler proxy tier preference
    # Options: residential | datacenter | tor | direct
    default_proxy_tier: str = "tor"  # fallback tier if crawler doesn't specify

    # I2P (Invisible Internet Project) — alternative to Tor
    i2p_socks: str = ""  # "socks5://127.0.0.1:4447" when I2P is running
    i2p_enabled: bool = False

    # Proxy timing & evasion
    human_delay_min: float = 1.5  # seconds
    human_delay_max: float = 6.0
    jitter_enabled: bool = True  # add ±20% random jitter to delays
    rotate_user_agent: bool = True
    rotate_tls_fingerprint: bool = True  # use curl-cffi impersonation


settings = Settings()
