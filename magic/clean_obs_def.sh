#!/usr/bin/bash

if [ $# -ne 3 ]; then
	echo "Usage: $0 magic_exported.def cleaned.def magic_source.mag"
	exit 1
fi

python normalise_magic_def.py "$1" "$2" --verbose --mag-source "$3" --librelane-obstructions obs.json

