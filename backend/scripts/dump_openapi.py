"""Print the OpenAPI schema as JSON (used by `make gen-api`)."""

import json

from app.main import create_app

print(json.dumps(create_app().openapi(), indent=2))
