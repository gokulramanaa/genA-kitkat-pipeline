#!/bin/bash

# Quick development start script for Airflow DAG visualization
# This script sets up and starts Airflow using Docker Compose

set -e

echo "🚀 Starting Airflow for DAG visualization..."
echo ""

# Check if docker and docker-compose are available
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ docker-compose is not installed. Please install docker-compose first."
    exit 1
fi

# Use docker compose (v2) if available, otherwise docker-compose (v1)
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker compose"
else
    DOCKER_COMPOSE_CMD="docker-compose"
fi

# Set AIRFLOW_UID to current user ID if not set (prevents permission issues)
if [ -z "$AIRFLOW_UID" ]; then
    export AIRFLOW_UID=$(id -u)
    echo "📝 Setting AIRFLOW_UID=$AIRFLOW_UID"
fi

# Set project directory
export AIRFLOW_PROJ_DIR=$(pwd)

echo "📁 Project directory: $AIRFLOW_PROJ_DIR"
echo ""

# Create necessary directories
mkdir -p logs plugins
echo "✅ Created necessary directories (logs, plugins)"
echo ""

# Initialize Airflow (one-time setup)
echo "🔧 Initializing Airflow (this may take a moment on first run)..."
$DOCKER_COMPOSE_CMD up airflow-init

# Start Airflow services
echo ""
echo "🎯 Starting Airflow services..."
echo "   - Web UI will be available at: http://localhost:8080"
echo "   - Username: admin"
echo "   - Password: admin"
echo ""
echo "⏳ Starting services... (Press Ctrl+C to stop)"
echo ""

$DOCKER_COMPOSE_CMD up

