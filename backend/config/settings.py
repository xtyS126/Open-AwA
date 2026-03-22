from pydantic_settings import BaseSettings
from typing import Optional
import os
from config.experience_settings import experience_config


class Settings(BaseSettings):
    PROJECT_NAME: str = "Open-AwA AI Agent"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api"
    
    DATABASE_URL: str = "sqlite:///./openawa.db"
    
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    
    VECTOR_DB_PATH: str = "./data/vector_db"
    
    USAGE_RETENTION_DAYS: int = 365
    
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024
    ALLOWED_EXTENSIONS: set = {".txt", ".md", ".py", ".js", ".json", ".yaml", ".yml"}
    
    SANDBOX_TIMEOUT: int = 30
    SANDBOX_MEMORY_LIMIT: str = "512m"
    
    LOG_LEVEL: str = "INFO"
    
    experience_extraction_enabled: bool = True
    experience_retrieval_enabled: bool = True
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
