#!/bin/bash

# run.sh - Script de inicio para Render
export RENDER=true

# Opción 1: Con archivo de configuración (recomendado)
# gunicorn main:app -c gunicorn.conf.py

# Opción 2: Con parámetros directos (más simple)
gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:$PORT --timeout 120 --log-level info main:app
