LAUNCHER="launch_$clean_name.sh"
cat <<EOF > "$LAUNCHER"
#!/bin/bash
cd "$TARGET_DIR"
source venv/bin/activate

# Automated Dependency Check
if [ -f "requirements.txt" ]; then
    echo "Syncing dependencies..."
    pip install -q -r requirements.txt
fi

echo "Starting $clean_name..."
python3 main.py
EOF

chmod +x "$LAUNCHER"
