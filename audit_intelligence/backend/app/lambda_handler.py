"""Lambda entrypoint for the HTTP API."""

from mangum import Mangum

from app.main import app

handler = Mangum(app, lifespan="off")
