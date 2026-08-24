#!/bin/bash
# SmartAlarms API Server Startup Script

cd "$(dirname "$0")"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -q -r requirements.txt

# Start the server
echo "Starting SmartAlarms API server..."
python3 -m uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload
