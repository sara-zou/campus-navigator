"""Entry point for uvicorn: `uvicorn main:app`. Kept separate so importing api doesn't load data."""
from api import create_app

app = create_app()
