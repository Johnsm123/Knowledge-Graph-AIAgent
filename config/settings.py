"""
Configuration settings for Medical AI Agent System
"""
import os
from pydantic_settings import BaseSettings
from typing import Optional

# Always resolve .env relative to this file (project root/config/../.env)
_ENV_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Neo4j Aura Configuration
    neo4j_uri: str
    neo4j_username: str = "neo4j"
    neo4j_password: str
    neo4j_database: str = "neo4j"
    aura_instanceid: str = ""
    
    # AWS Bedrock Configuration
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "amazon.nova-pro-v1:0"

    # Azure Communication Services
    azure_communication_connection_string: str = ""
    azure_communication_sender: str = ""

    # Neo4j Reference Database Configuration
    neo4j_ref_uri: str = ""
    neo4j_ref_username: str = ""
    neo4j_ref_password: str = ""
    neo4j_ref_database: str = "neo4j"

    # Google Maps / Places API
    google_maps_api_key: str = ""

    # Application Configuration
    debug: bool = False
    log_level: str = "INFO"
    
    class Config:
        env_file = _ENV_FILE
        case_sensitive = False


settings = Settings()
