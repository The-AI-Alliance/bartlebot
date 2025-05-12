#!/usr/bin/env bash

echo "Legal Integration Test"

JSONL_FILE=test-enrichments.jsonl
MILVUS_URI=file://test-legal-milvus.db

echo "Building resources"

python -m bartlebot.bin.cli legal build --config-file ../bartlebot.yml --verbose

echo "Answer default legal question"

echo "" | python -m bartlebot.bin.cli legal handle --config-file ../bartlebot.yml --verbose

#rm -f $JSONL_FILE
#rm -f test-legal-milvus.db
