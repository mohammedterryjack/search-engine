#!/bin/sh
set -e

MODEL_NAME="${SEARCHY_SUMMARIZER_MODEL:-qwen3.5:0.8b}"
export OLLAMA_HOST="${OLLAMA_HOST:-0.0.0.0:11434}"

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

echo "Pulling ${MODEL_NAME} model..."
ollama pull "${MODEL_NAME}"

echo "Model ready, keeping server running..."
wait $SERVER_PID
