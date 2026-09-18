#!/bin/sh

set -e

echo "Starting Initialization Job for TierX..."

MODEL=${TIERX_OLLAMA_MODEL:-${OLLAMA_MODEL:-${SOC_MIND_OLLAMA_MODEL:-phi3}}}

echo "Checking if model '$MODEL' is already present in Ollama..."
if curl -s http://ollama:11434/api/tags | grep -q "\"name\":\"$MODEL"; then
    echo "Model '$MODEL' is already present. Skipping pull."
else
    echo "Pulling model '$MODEL' from Ollama. This may take a few minutes depending on connectivity..."
    RESPONSE=$(curl --fail --silent --show-error -X POST http://ollama:11434/api/pull -d "{\"name\": \"$MODEL\"}")
    echo "$RESPONSE"
    if echo "$RESPONSE" | grep -q '"error"'; then
        echo "Ollama reported a model pull error." >&2
        exit 1
    fi
    if ! curl --fail --silent http://ollama:11434/api/tags | grep -q "\"name\":\"$MODEL"; then
        echo "Model '$MODEL' was not present after the pull completed." >&2
        exit 1
    fi
    echo ""
    echo "Model '$MODEL' pulled successfully."
fi

echo "Running idempotent database schema initializations..."

echo "Initialization Complete."
exit 0
