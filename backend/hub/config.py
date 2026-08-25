from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Endpoint OpenAI-compatible của Gemini — cùng hình dạng /chat/completions.
GEMINI_OPENAI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"


class Settings(BaseSettings):
    # Research SPY để bí mật ở `backend/.env.local` (xem .gitignore). Vẫn đọc `.env` sau đó
    # để bản chép từ dự án gốc chạy được ngay mà không phải đổi tên file.
    model_config = SettingsConfigDict(env_file=(".env.local", ".env"), extra="ignore")

    # --- LLM ---
    # Dùng tên biến RIÊNG (LLM_*) để KHÔNG bị env ANTHROPIC_* của Claude Code trên máy đè.
    llm_api_key: str = ""                   # API key trực tiếp (nếu có)
    llm_auth_token: str = ""                # token Bearer cho gateway
    llm_base_url: str = ""                  # URL gateway OpenAI-compatible

    # Khoá Gemini dùng CHUNG với phần còn lại của Research SPY (lib/keywords/gloss.py,
    # lib/ads/keyword_extract.py…). Khai một chỗ trong `backend/.env.local` là cả webtool lẫn
    # Hub cùng dùng. Chép khoá ra hai biến khác nhau là mời một lỗi rất khó thấy: xoay khoá ở
    # một chỗ thì chỗ kia lặng lẽ hỏng, mà Hub hỏng LLM thì nó rơi về heuristic chứ không báo.
    gemini_api_key: str = ""

    # Model tiering để TỐI ƯU CHI PHÍ: việc nhẹ dùng bản lite, tổng hợp dùng bản đầy.
    # Đo 2026-08-25 trên khoá đang dùng: cả hai trả JSON hợp lệ trong ~2-6s, thừa sức trong
    # trần 1024 token của `llm.complete_json`.
    model_cheap: str = "gemini-3.5-flash-lite"   # clean/normalize số lượng lớn
    model_smart: str = "gemini-3.5-flash"        # tổng hợp insight/forecast/recs

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
    def effective_api_key(self) -> str:
        """Khoá thật sự gửi đi, theo thứ tự ưu tiên. `LLM_*` khai tường minh thì thắng."""
        return (self.llm_auth_token or self.llm_api_key or self.gemini_api_key).strip()

    @property
    def effective_base_url(self) -> str:
        """Gốc URL OpenAI-compatible. Không khai `LLM_BASE_URL` mà có khoá Gemini thì về Gemini.

        Gemini CÓ endpoint OpenAI-compatible, nên `llm.py` không phải biết gì về Gemini —
        vẫn POST /chat/completions như với mọi gateway khác. Đo 2026-08-25: chạy đúng.
        """
        if self.llm_base_url.strip():
            return self.llm_base_url.strip().rstrip("/")
        if self.gemini_api_key.strip():
            return GEMINI_OPENAI_BASE
        return ""

    @property
    def llm_enabled(self) -> bool:
        # PHẢI có cả khoá lẫn URL. Bản gốc cho qua khi chỉ có `llm_api_key` — mà `llm.py` lại
        # dựng URL từ `llm_base_url`, nên thiếu URL là nó gọi vào "/chat/completions" cụt đầu
        # và ném lỗi, trong khi `enabled()` vẫn nói True.
        return bool(self.effective_api_key and self.effective_base_url)

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
