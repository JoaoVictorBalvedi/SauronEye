#!/bin/bash
set -e

ollama serve &
sleep 2

for i in $(seq 1 30); do
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        break
    fi
    sleep 2
done

MODEL="${LLM_MODEL:-llama3.2}"
ollama pull "$MODEL"

exec uvicorn main:app --host 0.0.0.0 --port 7860
