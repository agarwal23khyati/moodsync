#!/usr/bin/env bash
# Run AFTER START.sh is up. Produces results/results.md, figures and paper_text.md
cd "$(dirname "$0")" && source backend/venv/bin/activate && python experiments/run_experiments.py
