#!/bin/sh
set -e

echo "Starting Ollama server..."
ollama serve &
SERVER_PID=$!

echo "Waiting for Ollama server to be ready..."
sleep 5

echo "Pulling qwen2.5:0.5b-instruct model..."
ollama pull qwen2.5:0.5b-instruct

echo "Model ready, keeping server running..."
wait $SERVER_PID
