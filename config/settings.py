"""
Configuration settings for Medical AI Agent System
"""
import os
from pydantic_settings import BaseSettings
from typing import Optional

# Resolve .env to an absolute path anchored at the repo root so settings load
# correctly regardless of the caller's current working directory (e.g. when
# scripts/ utilities are run from inside scripts/).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_FILE = os.path.join(_REPO_ROOT, ".env")


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

    # Neo4j Persona-Demo Database (bulk-upload persona-comparison animation)
    neo4j_persona_uri: str = ""
    neo4j_persona_user: str = ""
    neo4j_persona_password: str = ""

    # Google Maps / Places API
    google_maps_api_key: str = ""

    # Application Configuration
    debug: bool = False
    log_level: str = "INFO"
    
    class Config:
        env_file = _ENV_FILE
        case_sensitive = False
        # Allow ad-hoc env vars used by other modules (e.g.
        # CARE_GAP_ENABLED_MEASURES read via os.environ) to coexist in
        # .env without needing a Settings field for each.
        extra = "ignore"


settings = Settings()
