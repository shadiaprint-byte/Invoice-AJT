#!/bin/bash
# QuickInvoice launcher for Mac / Linux
echo "============================================"
echo "  QuickInvoice - Invoicing Software"
echo "============================================"
echo ""
echo "Starting the application..."
echo ""

if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] Python 3 is not installed."
    echo "Install it from https://www.python.org/downloads/"
    exit 1
fi

python3 server.py
