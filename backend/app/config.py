from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    demo_mode: bool = False
    app_cookie_secure: bool = True
    app_allowed_origin: str = 'http://localhost:5173'
    app_db_path: Path = Path('./data/nutrition.db')
    app_media_dir: Path = Path('./data/media')
    app_nginx_accel: bool = False
    app_max_ai_concurrency: int = 10
    # BiSheng 1.3.1 is only called for nutrition report generation.
    bisheng_report_url: str = ''
    bisheng_report_api_key: str = ''
    bisheng_report_workflow_id: str = ''
    bisheng_report_input_key: str = 'report_context'
    vllm_chat_completions_url: str = ''
    vllm_api_key: str = ''
    vllm_model: str = 'Qwen3.5-27B-FP8'
    vllm_max_tokens: int = 768
    vllm_vision_url: str = ''
    vllm_vision_model: str = ''
    vllm_vision_api_key: str = ''

@lru_cache

def get_settings() -> Settings:
    return Settings()
