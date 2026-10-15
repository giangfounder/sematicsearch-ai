"""Cấu hình toàn cục. Mọi hệ số/ngưỡng mặc định nằm ở đây; có thể override theo demo
qua demos.settings (hệ số chấm điểm) và demos.thresholds (ngưỡng đã calibrate)."""
from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Gemini
    gemini_api_key: str = ""
    gemini_provider: str = "gemini"  # gemini | fake
    gemini_llm_model: str = "gemini-3.5-flash-lite"
    gemini_rerank_model: str = "gemini-3.5-flash-lite"
    gemini_embed_model: str = "gemini-embedding-001"
    gemini_thinking_level: str = "minimal"
    embed_dim: int = 768
    understand_timeout_ms: int = 1200
    embed_timeout_ms: int = 800
    rerank_timeout_ms: int = 2500
    # >0: không chờ understand quá mốc này (ms) khi không có ngữ cảnh; 0 = luôn chờ tới timeout
    understand_soft_deadline_ms: int = 0
    # Hạn chót tổng cho 1 truy vấn (ms). 0 = tắt. Bảo đảm kết quả luôn trả trong ngân sách này
    # (hết giờ thì dùng rule + embedding + thứ tự chưa rerank). Chừa phần cho mạng về client.
    search_deadline_ms: int = 1800
    # không khởi động rerank nối tiếp nếu ngân sách còn lại dưới mức này
    rerank_min_budget_ms: int = 900
    # ước lượng thời gian 1 lần rerank; không khởi động rerank nếu ngân sách còn lại nhỏ hơn mức này
    rerank_expected_ms: int = 1400
    offline_timeout_ms: int = 60000
    key_cooldown_s: float = 30.0
    breaker_failures: int = 5
    breaker_open_s: float = 20.0
    gemini_max_concurrency: int = 16
    # OpenAI-compatible (GPT) – dùng làm nguồn dự phòng khi Gemini hết quota.
    # Trống key = tắt hoàn toàn, không thay đổi hành vi hiện tại.
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_llm_model: str = "gpt-4o-mini"
    openai_embed_model: str = "text-embedding-3-small"
    # giới hạn request embed GPT/phút (0 = không giới hạn, tự xoay key khi 429)
    openai_embed_rpm: int = 0
    # Tự động chuyển sang GPT khi provider chính hết quota / mở breaker.
    gpt_fallback: bool = True

    # Free tier: 100 request/phút cho embed (mỗi văn bản trong batch tính 1). Paid tier: tăng lên 3000+
    embed_doc_rpm: int = 90
    embed_batch_size: int = 30
    embed_concurrency: int = 1
    job_concurrency: int = 2
    llm_offline_rpm: int = 30
    llm_rpm_limit: int = 0

    # DB
    database_url: str = "postgresql://semsearch:change-me@localhost:5432/semsearch"
    version_poll_s: float = 30.0

    # Auth
    api_keys: str = ""
    admin_keys: str = ""
    # Fernet: lưu bản mã của khóa bảng để chủ bảng xem lại; trống = chỉ lưu hash như trước.
    table_key_encryption_key: SecretStr = SecretStr("")
    # Tài khoản tạo sẵn khi khởi động (để trống email = không seed, giữ chế độ dev-mở cho test)
    seed_account_email: str = ""
    seed_account_password: str = ""
    seed_account_name: str = ""
    seed_account_phone: str = ""
    # Đăng nhập Google (OAuth ID token). Trống = ẩn nút đăng nhập Google.
    google_client_id: str = ""
    # Cho phép tạo tài khoản mới khi đăng nhập Google lần đầu (False = chỉ tài khoản đã có mới vào được)
    google_allow_signup: bool = True

    # Cache
    response_cache_ttl: int = 600
    understand_cache_ttl: int = 3600
    embed_cache_ttl: int = 86400
    cache_size: int = 5000

    # Flags
    embed_rewritten: bool = False
    # cache bền (Postgres) cho embedding câu hỏi / understanding khi search online (evaluate luôn bật)
    persistent_cache_online: bool = False
    load_on_startup: bool = True

    @property
    def gemini_keys(self) -> list[str]:
        return [k.strip() for k in self.gemini_api_key.split(",") if k.strip()]

    @property
    def openai_keys(self) -> list[str]:
        return [k.strip() for k in self.openai_api_key.split(",") if k.strip()]

    @property
    def gpt_enabled(self) -> bool:
        return bool(self.gpt_fallback) and bool(self.openai_keys)

    @property
    def api_key_set(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    @property
    def admin_key_set(self) -> set[str]:
        return {k.strip() for k in self.admin_keys.split(",") if k.strip()}


# ---- Hệ số mặc định của pipeline (giải thích trong README) ----
DEFAULT_SCORING: dict = {
    # trọng số theo loại vector khi lấy max (dense theo sản phẩm)
    "kind_weights": {"question": 1.0, "name": 0.97, "use_case": 0.93, "profile": 0.90},
    # RRF
    "rrf_k": 20,
    "rrf_weights": {"dense": 1.0, "bm25": 0.8, "entity": 1.5},
    # BM25 theo trường
    "bm25_field_weights": {"name": 1.0, "profile": 0.6},
    # chuẩn hoá cosine về 0..1
    "cos_lo": 0.55,
    "cos_hi": 0.85,
    # raw = Σ a_i * tín hiệu_i
    "a": {"cos": 0.45, "rrf": 0.20, "entity": 0.20, "soft": 0.10, "stock": 0.03, "prev": 0.02},
    # approx (tầm/khoảng) -> dải cứng ±
    "approx_band": 0.20,
    # rerank
    "rerank_top": 6,
    "rerank_beta": 0.6,
    "rerank_violate_penalty": 0.6,
    "rerank_missing_relevance": 0.3,
    "retrieve_top": 30,
}

DEFAULT_THRESHOLDS: dict = {
    "platt_a": 10.0,
    "platt_b": -5.0,
    "t_match": 0.70,
    "t_min": 0.35,
    "margin": 0.08,
    "margin_amb": 0.10,
    "gate_high": 0.85,
    "gate_margin": 0.15,
}

DEFAULT_FILLERS = [
    "dạ", "ạ", "vâng", "ừ", "ừm", "ờ", "à", "ơ", "alo", "a lô", "allo", "dạ vâng", "vâng ạ",
    "ừ thì", "thì là", "kiểu như", "cho em hỏi", "cho mình hỏi", "cho tôi hỏi", "em hỏi",
    "chị ơi", "anh ơi", "em ơi", "bạn ơi", "shop ơi", "ạ ạ", "nhé", "nha", "hả", "hử",
]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def merged(base: dict, override: dict | None) -> dict:
    """Gộp dict 2 tầng (override theo demo)."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out

