#!/bin/bash
set -e

# Change directory to the script's root directory
cd "$(dirname "$0")"

# Initialize virtual environment if needed
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate

# Ensure pip is up to date
pip install --upgrade pip

# Install PyTorch with CUDA 13.0 support directly from PyTorch's repository
echo "Verifying / Installing PyTorch (CUDA 13.0)..."
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu130

# Sync remaining project dependencies
if [ -f "requirements.txt" ]; then
    echo "Syncing dependencies from requirements.txt..."
    pip install -r requirements.txt
fi

echo "Starting Calypso..."
python3 core.py
