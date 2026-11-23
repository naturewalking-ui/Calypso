#!/bin/bash
set -euo pipefail

# Always run from the directory containing this script
cd "$(dirname "$0")"

# 1. Install global system dependencies
echo "Installing system packages..."
sudo apt update && sudo apt install -y \
    git \
    build-essential \
    cmake \
    ffmpeg \
    espeak-ng \
    libsndfile1 \
    libgl1 \
    libglib2.0-0 \
    python3-tk \
    portaudio19-dev \
    libasound2-dev \
    python3-dev \
    python3-venv

# 2. Initialize virtual environment if needed
if [ ! -x "venv/bin/python" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# 3. Upgrade pip and build tools
echo "Upgrading pip..."
venv/bin/python -m pip install --upgrade pip setuptools wheel

# 4. Install PyTorch with CUDA 13.0 wheels
echo "Verifying / Installing PyTorch (CUDA 13.0)..."
venv/bin/python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu130

# 5. Sync project dependencies
if [ -f "requirements.txt" ]; then
    echo "Syncing dependencies from requirements.txt..."
    venv/bin/python -m pip install -r requirements.txt
else
    echo "Warning: requirements.txt not found. Skipping dependency sync."
fi

# 6. Initialize local NLTK data directory (owner-only permissions for NLTK >= 3.10)
echo "Downloading NLTK VADER lexicon into ./nltk_data..."
mkdir -p nltk_data
chmod 700 nltk_data
venv/bin/python -c "import nltk; nltk.download('vader_lexicon', download_dir='nltk_data')"
chmod -R go-w nltk_data

echo ""
echo "========================================"
echo "  Calypso installation complete!"
echo "  You can now run ./launch.sh to start."
echo "========================================"
if [ -t 0 ]; then
    read -r -p "Press Enter to close..."
fi
