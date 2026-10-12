#!/usr/bin/bash

rm -rf runs/anton
mkdir -p runs/anton
#librelane --run-tag anton --force-run-dir runs/anton config.json ../magic/obs.json

if which docker; then
    docker_args="--docker-no-tty --dockerized"
else
    docker_args=""
fi

# Base config:
CONFIGS=config.json
# Also include macros:
CONFIGS="$CONFIGS macro.json"
# Also use our custom DEF:
CONFIGS="$CONFIGS customdef.json"

time librelane $docker_args --run-tag anton --force-run-dir runs/anton $CONFIGS

