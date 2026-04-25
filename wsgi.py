"""Production WSGI entry point for Azure App Service / gunicorn.

Run with:
  gunicorn --worker-class geventwebsocket.gunicorn.workers.GeventWebSocketWorker \
           --workers 1 --bind 0.0.0.0 wsgi:app
"""
import logging

# Monkey-patch for gevent — MUST come before any networking import
from gevent import monkey
monkey.patch_all()

from src.care_gap_api import app, socketio  # noqa: E402,F401  (registers blueprints)

logger = logging.getLogger(__name__)

try:
    from src.mobile_reminders import start_mobile_reminder_scheduler
    start_mobile_reminder_scheduler()
except Exception as exc:
    logger.warning(f"Mobile reminder scheduler failed to start: {exc}")

# One-time hygiene pass on every container start: backfill primary CPT/ICD codes
# from the golden reference and delete duplicate (member, measure) gaps. Idempotent.
try:
    from src.care_gap_cleanup import cleanup_all
    stats = cleanup_all()
    logger.info(f"[STARTUP] Care-gap hygiene complete: {stats}")
except Exception as exc:
    logger.warning(f"[STARTUP] care-gap cleanup skipped: {exc}")

try:
    from src.persona_sync import bootstrap_persona_schema
    bootstrap_persona_schema()
    logger.info("Persona reference DB schema ready")
except Exception as exc:
    logger.warning(f"Persona schema bootstrap skipped: {exc}")

try:
    from src.noshow_scheduler import start_scheduler
    start_scheduler()
except Exception as exc:
    logger.warning(f"No-show scheduler failed to start: {exc}")
