#!/bin/bash
set -e

pip install -q -r requirements.txt 2>&1 | tail -1

echo "Post-merge setup complete."
