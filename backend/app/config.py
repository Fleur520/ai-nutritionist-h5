from functools import lru_cache
from pathlib import Path
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    demo_mode: bool = False
    app_cookie_secure: bool = True
    app_allowed_origin: str = 'http://localhost:5173'
    app_db_engine: Literal['sqlite', 'mysql'] = 'sqlite'
    app_db_path: Path = Path('./data/nutrition.db')
    mysql_host: str = '127.0.0.1'
    mysql_port: int = Field(3306, ge=1, le=65535)
    mysql_user: str = 'nutrition'
    mysql_password: str = ''
    mysql_database: str = 'ai_nutritionist'
    mysql_connect_timeout: int = Field(10, ge=1, le=60)
    app_media_dir: Path = Path('./data/media')
    app_nginx_accel: bool = False
    app_max_ai_concurrency: int = 10
    app_max_image_concurrency: int = Field(4, ge=1, le=32)
    app_reports_enabled: bool = True
    app_revision: str = 'local'
    # Keep report generation separate from the image recognition workflow.
    food_recognition_provider: Literal['direct', 'bisheng'] = 'direct'
    bisheng_recognition_base_url: str = ''
    bisheng_recognition_workflow_id: str = ''
    bisheng_recognition_api_key: str = ''
    bisheng_recognition_input_field: Literal['input', 'user_input'] = 'input'
    bisheng_recognition_image_key: str = 'meal_image'
    bisheng_recognition_timeout: int = Field(240, ge=30, le=280)
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
    vllm_vision_max_tokens: int = Field(1536, ge=128, le=16384)
    vllm_vision_enable_thinking: bool = False

@lru_cache

def get_settings() -> Settings:
    return Settings()
