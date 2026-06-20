"""
Configuration management using pydantic-settings.
All settings are loaded from environment variables and .env file.
"""
from functools import lru_cache

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AnthropicSettings(BaseSettings):
    """Anthropic API settings."""

    api_key: str = Field(..., alias="ANTHROPIC_API_KEY")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


class NaverSettings(BaseSettings):
    """Naver API settings."""

    # Naver Search API
    client_id: str = Field(..., alias="NAVER_CLIENT_ID")
    client_secret: str = Field(..., alias="NAVER_CLIENT_SECRET")

    # Naver Commerce API
    commerce_client_id: str = Field(..., alias="NAVER_COMMERCE_CLIENT_ID")
    commerce_client_secret: str = Field(..., alias="NAVER_COMMERCE_CLIENT_SECRET")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


class NaverSearchAdSettings(BaseSettings):
    """
    Naver Search Ad (검색광고) API settings.

    Used by the Keyword Tool (``/keywordstool``) which is the only source of
    absolute monthly search volume (월간검색수). Credentials are issued from
    the 검색광고 management UI: 도구 > API 사용 관리.
    """

    api_key: str = Field(..., alias="NAVER_SEARCHAD_API_KEY")
    secret_key: str = Field(..., alias="NAVER_SEARCHAD_SECRET_KEY")
    customer_id: str = Field(..., alias="NAVER_SEARCHAD_CUSTOMER_ID")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


class AliExpressSettings(BaseSettings):
    """AliExpress API settings."""

    app_key: str = Field(..., alias="ALI_APP_KEY")
    app_secret: str = Field(..., alias="ALI_APP_SECRET")
    tracking_id: str = Field(..., alias="ALI_TRACKING_ID")
    # Ask AliExpress to return prices ALREADY converted to this currency, so we
    # never guess an FX rate for the source price. KRW = native won straight from
    # the API (AliExpress applies its own buyer-side FX, which is what we pay).
    target_currency: str = Field(default="KRW", alias="ALI_TARGET_CURRENCY")
    target_language: str = Field(default="EN", alias="ALI_TARGET_LANGUAGE")
    # Dropshipping (DS) API OAuth tokens. The DS API (aliexpress.ds.*) needs a
    # user access_token; obtain via OAuth and refresh via /rest/auth/token/refresh.
    # Empty -> DS client unavailable (falls back to the affiliate client).
    access_token: str = Field(default="", alias="ALI_ACCESS_TOKEN")
    refresh_token: str = Field(default="", alias="ALI_REFRESH_TOKEN")
    token_expire_at: str = Field(default="", alias="ALI_TOKEN_EXPIRE_AT")
    # DS search locale/ship-to (KR market).
    ship_to_country: str = Field(default="KR", alias="ALI_SHIP_TO_COUNTRY")
    search_locale: str = Field(default="ko_KR", alias="ALI_SEARCH_LOCALE")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


class DatabaseSettings(BaseSettings):
    """Database settings."""

    url: PostgresDsn = Field(..., alias="DATABASE_URL")
    echo: bool = Field(default=False, alias="DATABASE_ECHO")
    pool_size: int = Field(default=5, alias="DATABASE_POOL_SIZE")
    max_overflow: int = Field(default=10, alias="DATABASE_MAX_OVERFLOW")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


class RedisSettings(BaseSettings):
    """Redis settings."""

    url: RedisDsn = Field(..., alias="REDIS_URL")
    max_connections: int = Field(default=10, alias="REDIS_MAX_CONNECTIONS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


class TelegramSettings(BaseSettings):
    """Telegram notification settings."""

    bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    chat_id: str = Field(..., alias="TELEGRAM_CHAT_ID")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


class ExchangeRateSettings(BaseSettings):
    """Exchange rate API settings."""

    api_key: str = Field(..., alias="EXCHANGE_RATE_API_KEY")
    base_url: str = Field(
        default="https://api.exchangerate-api.com/v4/latest/",
        alias="EXCHANGE_RATE_BASE_URL",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


class AppSettings(BaseSettings):
    """General application settings."""

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    debug: bool = Field(default=False, alias="DEBUG")

    # API server settings
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    # Worker settings
    max_workers: int = Field(default=4, alias="MAX_WORKERS")
    batch_size: int = Field(default=10, alias="BATCH_SIZE")

    # Retry settings
    max_retries: int = Field(default=3, alias="MAX_RETRIES")
    retry_delay: int = Field(default=5, alias="RETRY_DELAY")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return v_upper

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """Validate environment."""
        valid_envs = ["development", "staging", "production"]
        v_lower = v.lower()
        if v_lower not in valid_envs:
            raise ValueError(f"environment must be one of {valid_envs}")
        return v_lower

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


class Settings(BaseSettings):
    """
    Main settings class that aggregates all settings categories.
    """

    # Category settings
    app: AppSettings = Field(default_factory=AppSettings)
    anthropic: AnthropicSettings = Field(default_factory=AnthropicSettings)
    naver: NaverSettings = Field(default_factory=NaverSettings)
    searchad: NaverSearchAdSettings = Field(default_factory=NaverSearchAdSettings)
    aliexpress: AliExpressSettings = Field(default_factory=AliExpressSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    exchange_rate: ExchangeRateSettings = Field(default_factory=ExchangeRateSettings)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    def __init__(self, **kwargs):
        """Initialize settings with all category settings."""
        super().__init__(**kwargs)
        # Initialize all category settings
        self.app = AppSettings()
        self.anthropic = AnthropicSettings()
        self.naver = NaverSettings()
        self.searchad = NaverSearchAdSettings()
        self.aliexpress = AliExpressSettings()
        self.database = DatabaseSettings()
        self.redis = RedisSettings()
        self.telegram = TelegramSettings()
        self.exchange_rate = ExchangeRateSettings()


@lru_cache
def get_settings() -> Settings:
    """
    Get settings instance (singleton pattern).

    Returns:
        Settings instance with all configuration loaded from environment.
    """
    return Settings()
