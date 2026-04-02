#!/usr/bin/env python3
"""
Neo4j Setup Script for HEDIS Golden Reference Persona System
Helps install and configure Neo4j for the persona knowledge graph
"""

import subprocess
import sys
import os
import time
import requests
from pathlib import Path

def check_neo4j_running():
    """Check if Neo4j is running on default port"""
    try:
        response = requests.get("http://localhost:7474", timeout=5)
        return response.status_code == 200
    except:
        return False

def install_neo4j_desktop():
    """Instructions for installing Neo4j Desktop"""
    print("\n" + "="*60)
    print("NEO4J INSTALLATION INSTRUCTIONS")
    print("="*60)
    print("1. Download Neo4j Desktop from: https://neo4j.com/download/")
    print("2. Install Neo4j Desktop")
    print("3. Create a new project")
    print("4. Add a local DBMS with:")
    print("   - Name: HEDIS-Personas")
    print("   - Password: hedis123")
    print("   - Version: 5.x (latest)")
    print("5. Start the database")
    print("6. The database will be available at bolt://localhost:7687")
    print("\nAlternatively, use Docker:")
    print("docker run -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/hedis123 neo4j:latest")

def check_docker_neo4j():
    """Check if Docker is available and can run Neo4j"""
    try:
        result = subprocess.run(["docker", "--version"], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print(f"Docker found: {result.stdout.strip()}")
            return True
    except:
        pass
    return False

def start_docker_neo4j():
    """Start Neo4j using Docker"""
    print("\nStarting Neo4j with Docker...")
    try:
        # Stop any existing container
        subprocess.run(["docker", "stop", "hedis-neo4j"], 
                      capture_output=True, timeout=10)
        subprocess.run(["docker", "rm", "hedis-neo4j"], 
                      capture_output=True, timeout=10)
        
        # Start new container
        cmd = [
            "docker", "run", "-d",
            "--name", "hedis-neo4j",
            "-p", "7474:7474",
            "-p", "7687:7687",
            "-e", "NEO4J_AUTH=neo4j/hedis123",
            "-e", "NEO4J_PLUGINS=[\"apoc\"]",
            "neo4j:latest"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print("Neo4j container started successfully!")
            print("Waiting for Neo4j to be ready...")
            
            # Wait for Neo4j to be ready
            for i in range(30):
                if check_neo4j_running():
                    print("Neo4j is ready!")
                    print("Web interface: http://localhost:7474")
                    print("Bolt connection: bolt://localhost:7687")
                    print("Username: neo4j")
                    print("Password: hedis123")
                    return True
                time.sleep(2)
                print(f"Waiting... ({i+1}/30)")
            
            print("Neo4j container started but may still be initializing")
            return True
        else:
            print(f"Failed to start Neo4j container: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"Error starting Docker Neo4j: {e}")
        return False

def main():
    print("HEDIS GOLDEN REFERENCE PERSONA SYSTEM - NEO4J SETUP")
    print("="*60)
    
    # Check if Neo4j is already running
    if check_neo4j_running():
        print("✓ Neo4j is already running at http://localhost:7474")
        print("You can now run the persona system!")
        return
    
    print("Neo4j is not running. Let's set it up...")
    
    # Check Docker option
    if check_docker_neo4j():
        choice = input("\nWould you like to start Neo4j using Docker? (y/n): ").lower()
        if choice == 'y':
            if start_docker_neo4j():
                print("\n✓ Neo4j is now running!")
                print("You can now run: python run_system.py")
                return
    
    # Provide manual installation instructions
    install_neo4j_desktop()
    
    print("\n" + "="*60)
    print("After setting up Neo4j, run: python run_system.py")
    print("="*60)

if __name__ == "__main__":
    main()