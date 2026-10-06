#!/usr/bin/bash

rm -rf runs/anton
mkdir -p runs/anton
librelane --run-tag anton --force-run-dir runs/anton config.json ../magic/obs.json

