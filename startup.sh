#!/bin/bash
gunicorn --bind=0.0.0.0 --timeout 600 --worker-class geventwebsocket.gunicorn.workers.GeventWebSocketWorker --workers 1 wsgi:app
