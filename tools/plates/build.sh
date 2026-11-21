#!/bin/sh
# Build the two picture helpers (macOS only; needs the Xcode command line tools).
set -e
cd "$(dirname "$0")"
mkdir -p bin
swiftc -O subject.swift -o bin/subject
swiftc -O plate.swift -o bin/plate
echo "built tools/plates/bin/subject and tools/plates/bin/plate"
