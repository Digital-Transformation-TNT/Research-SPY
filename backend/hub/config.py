from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Research SPY để bí mật ở `backend/.env.local` (xem .gitignore). Vẫn đọc `.env` sau đó
    # để bản chép từ dự án gốc chạy được ngay mà không phải đổi tên file.
    model_config = SettingsConfigDict(env_file=(".env.local", ".env"), extra="ignore")

    # --- LLM ---
    # Dùng tên biến RIÊNG (LLM_*) để KHÔNG bị env ANTHROPIC_* của Claude Code trên máy đè.
    llm_api_key: str = ""                   # API key Anthropic trực tiếp (nếu có)
    llm_auth_token: str = ""                # token Bearer cho gateway BTC
    llm_base_url: str = ""                  # URL gateway BTC
    # Model tiering để TỐI ƯU CHI PHÍ: việc nhẹ dùng Haiku, tổng hợp dùng Sonnet
    model_cheap: str = "claude-haiku-4-5-20251001"   # clean/normalize số lượng lớn
    model_smart: str = "claude-sonnet-5"             # tổng hợp insight/forecast/recs

    # --- Etsy ---
    etsy_keystring: str = ""
    etsy_shared_secret: str = ""

    @property
    def etsy_api_key(self) -> str:
        """Header x-api-key cho Etsy. App này yêu cầu dạng 'keystring:shared_secret'."""
        ks = self.etsy_keystring.strip()
        ss = self.etsy_shared_secret.strip()
        return f"{ks}:{ss}" if ks and ss else ks

    # --- Crawler ---
    # Anti-detect browser local API (AdsPower mặc định). Trống = fallback Playwright thường.
    antidetect_provider: str = ""           # "adspower" | "gologin" | "" (none)
    antidetect_api: str = "http://local.adspower.net:50325"
    antidetect_profile_id: str = ""
    crawl_delay_seconds: float = 4.0        # delay giữa request (tránh ban)
    crawl_max_items: int = 40               # số listing/keyword mỗi lần cào
    crawl_amazon_fetch_seller: bool = True  # cào tên shop THẬT từ trang /dp cho MỌI SP (chậm hơn nhưng đủ)

    cors_origins: str = "http://localhost:3000"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key.strip() or
                    (self.llm_auth_token.strip() and self.llm_base_url.strip()))

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
