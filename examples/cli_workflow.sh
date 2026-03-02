#!/bin/bash
# Example CLI workflow for Mnemo-Vault

# Set vault path
VAULT="~/knowledge-vault"

# 1. Create some memories
mnemo --vault $VAULT remember \
    --title "Project Setup" \
    --content "Initialized the project with Python 3.10 and FastAPI" \
    --type episodic \
    --tags project setup

mnemo --vault $VAULT remember \
    --title "FastAPI Basics" \
    --content "FastAPI is a modern Python web framework with automatic API docs" \
    --type semantic \
    --tags fastapi python

# 2. Index the vault
mnemo --vault $VAULT ingest

# 3. Query the vault
mnemo --vault $VAULT context \
    --query "Tell me about the project setup" \
    --tags project \
    --top-k 5

# 4. Interactive chat (requires Ollama)
# mnemo --vault $VAULT ask --chat --provider ollama --model llama3

# 5. Single question with Claude
# mnemo --vault $VAULT ask \
#     --query "What framework are we using?" \
#     --provider claude \
#     --model claude-3-5-sonnet-20240620

# 6. Check system status
mnemo --vault $VAULT doctor