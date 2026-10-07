#!/usr/bin/env bash
set -e

python_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
required="3.11"

if [ "$(printf '%s\n' "$required" "$python_version" | sort -V | head -n1)" != "$required" ]; then
    echo "Python $required+ required (found $python_version)"
    exit 1
fi

pip install -r requirements.txt
echo "Done. Run: python3 brickbreaker.py"
