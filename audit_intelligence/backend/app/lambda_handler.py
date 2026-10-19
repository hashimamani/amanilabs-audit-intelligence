"""Lambda entrypoint for the HTTP API. CloudFront forwards /api/* to the
gateway with the prefix intact; Mangum strips it so routes stay /cases etc."""

from mangum import Mangum

from app.main import app

handler = Mangum(app, lifespan="off", api_gateway_base_path="/api")
