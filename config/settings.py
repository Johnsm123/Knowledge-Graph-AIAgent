"""
Configuration settings for Medical AI Agent System
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Neo4j Configuration
    neo4j_uri: str = "neo4j+s://your-instance.neo4j.io"
    neo4j_username: str = "neo4j"
    neo4j_password: str
    neo4j_database: str = "neo4j"
    
    # OpenAI Configuration
    openai_api_key: str
    openai_model: str = "gpt-4"
    
    # Application Configuration
    debug: bool = False
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
