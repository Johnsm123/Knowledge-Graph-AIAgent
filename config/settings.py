"""
Configuration settings for Medical AI Agent System
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Neo4j Aura Configuration
    neo4j_uri: str
    neo4j_username: str = "neo4j"
    neo4j_password: str
    neo4j_database: str = "neo4j"
    aura_instanceid: str = ""
    
    # Azure OpenAI Configuration
    openai_api_key: str
    openai_model: str
    endpoint: str
    azure_openai_api_version: str = "2025-01-01-preview"

    # Azure Communication Services
    azure_communication_connection_string: str = ""
    azure_communication_sender: str = ""

    # Application Configuration
    debug: bool = False
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
