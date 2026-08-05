#!/bin/sh
set -eu
exec rq worker devdna --with-scheduler --url "$DEVDNA_REDIS_URL"
