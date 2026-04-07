#!/bin/sh
set -e

SUMMARY_MODEL="${SEARCHY_SUMMARY_MODEL:?Missing SEARCHY_SUMMARY_MODEL}"
AI_MODEL="${SEARCHY_AI_MODEL:?Missing SEARCHY_AI_MODEL}"
export OLLAMA_HOST="${OLLAMA_HOST:?Missing OLLAMA_HOST}"

echo "Starting Ollama server..."
ollama serve &
SERVER_PID=$!

echo "Waiting for Ollama server to be ready..."
ATTEMPTS=0
until ollama list >/dev/null 2>&1; do
  ATTEMPTS=$((ATTEMPTS + 1))
  if [ "$ATTEMPTS" -ge 60 ]; then
    echo "Ollama server did not become ready in time"
    exit 1
  fi
  sleep 2
done

echo "Pulling ${SUMMARY_MODEL} model..."
ollama pull "${SUMMARY_MODEL}"

echo "Pulling ${AI_MODEL} model..."
ollama pull "${AI_MODEL}"

echo "Model ready, keeping server running..."
wait $SERVER_PID
