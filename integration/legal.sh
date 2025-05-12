#!/usr/bin/env bash

echo "Legal Integration Test"

echo "Building resources"

python -m bartlebot.bin.bot legal build --config-file ../bartlebot.yml --verbose

echo "Handle default legal question"

echo "" | python -m bartlebot.bin.bot legal handle --config-file ../bartlebot.yml --verbose
