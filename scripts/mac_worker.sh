#!/bin/bash
set -eu
set -a
source "$HOME/.devdna/worker.env"
set +a
cd "$HOME/.devdna/app"
export PATH="$HOME/.devdna/app/.venv/bin:$PATH"
export PYTHONPATH="$HOME/.devdna/app/src"
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
exec rq worker devdna --with-scheduler --url "$DEVDNA_REDIS_URL"
