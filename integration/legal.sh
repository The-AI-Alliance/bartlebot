#!/usr/bin/env bash

echo "Legal Integration Test"

echo "Building resources"

python -m bartlebot.bin.cli legal build --config-file ../bartlebot.yml --verbose

echo "Answer default legal question"

echo "" | python -m bartlebot.bin.cli legal handle --config-file ../bartlebot.yml --verbose
