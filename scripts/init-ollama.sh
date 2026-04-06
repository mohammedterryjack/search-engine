#!/bin/sh
set -e

SUMMARY_MODEL="${SEARCHY_SUMMARY_MODEL:-qwen2.5:0.5b-instruct}"
AI_MODEL="${SEARCHY_AI_MODEL:-qwen3.5:0.8b}"
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

echo "Pulling ${SUMMARY_MODEL} model..."
ollama pull "${SUMMARY_MODEL}"

echo "Pulling ${AI_MODEL} model..."
ollama pull "${AI_MODEL}"

echo "Model ready, keeping server running..."
wait $SERVER_PID
