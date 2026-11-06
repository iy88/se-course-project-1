"""Application entrypoint.

The role is selected with ``APP_RUNTIME_ROLE`` (or ``app.manage serve-*``);
business configuration still comes only from the dotenv selected by
``APP_ENV_FILE``. ``app.main:app`` is the legacy combined single-process entry.
"""

from app.runtime import create_app

app = create_app()
