# Makefile for Medical AI Agent System

.PHONY: help install setup init run run-api clean test lint

help:
	@echo "Medical AI Agent System - Available Commands"
	@echo "============================================="
	@echo ""
	@echo "Setup Commands:"
	@echo "  make install       - Install dependencies"
	@echo "  make setup         - Create .env from template"
	@echo "  make init          - Initialize knowledge graph"
	@echo ""
	@echo "Run Commands:"
	@echo "  make run           - Run main application"
	@echo "  make run-api       - Run API server (port 5000)"
	@echo ""
	@echo "Utility Commands:"
	@echo "  make test          - Run tests"
	@echo "  make lint          - Run linting"
	@echo "  make clean         - Clean up generated files"
	@echo "  make format        - Format code"
	@echo ""
	@echo "Documentation:"
	@echo "  make docs          - Build documentation"
	@echo ""

# Setup
install:
	@echo "Installing dependencies..."
	pip install -r requirements.txt
	@echo "Dependencies installed!"

setup:
	@if [ ! -f .env ]; then \
		echo "Creating .env from template..."; \
		cp .env.example .env; \
		echo "Created .env - please edit with your credentials"; \
	else \
		echo ".env already exists"; \
	fi

init: setup
	@echo "Initializing knowledge graph..."
	python -m src.init_knowledge_graph
	@echo "Knowledge graph initialized!"

# Run
run:
	@echo "Starting Medical AI Application..."
	python -m src.main

run-api:
	@echo "Starting API Server on http://localhost:5000..."
	python -m src.api

# Development
test:
	@echo "Running tests..."
	pytest tests/ -v

lint:
	@echo "Running linters..."
	flake8 src/ --max-line-length=100 --ignore=E501,W503
	pylint src/ --disable=all --enable=E,F

format:
	@echo "Formatting code..."
	black src/ config/ --line-length=100
	isort src/ config/ --profile black

# Cleanup
clean:
	@echo "Cleaning up..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name ".DS_Store" -delete
	rm -rf .pytest_cache/ .mypy_cache/ htmlcov/
	@echo "Cleanup complete!"

# Documentation
docs:
	@echo "Building documentation..."
	@echo "Documentation files:"
	@echo "  - README.md (Main documentation)"
	@echo "  - GETTING_STARTED.md (Quick start guide)"
	@echo "  - ADVANCED_USAGE.md (Advanced features)"
	@echo "  - API_REFERENCE.md (API documentation)"
	@echo "  - PROJECT_SUMMARY.md (Project overview)"

# Docker
docker-build:
	docker build -t medical-ai-agent:latest .
	@echo "Docker image built successfully!"

docker-run:
	docker run -p 5000:5000 --env-file .env medical-ai-agent:latest

# Database
db-backup:
	@echo "Backing up Neo4j database..."
	# Implementation depends on Neo4j version and setup

db-restore:
	@echo "Restoring Neo4j database..."
	# Implementation depends on Neo4j version and setup

# Development environment
dev-setup: install setup
	@echo "Installing development tools..."
	pip install pytest pytest-cov flake8 pylint black isort
	@echo "Development environment ready!"

# All-in-one setup
all: dev-setup init
	@echo "Complete setup finished!"

# Version
version:
	@echo "Medical AI Agent System - Version 1.0.0"

.DEFAULT_GOAL := help
