@echo off
title Local LLM Studio - AI Operating Workspace
echo Starting Local LLM Studio Production Workspace...
echo Open your browser at http://localhost:8080
start http://localhost:8080
python -m uvicorn backend.server:app --host 0.0.0.0 --port 8080
pause
