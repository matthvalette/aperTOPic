"""Deploy the topic service (API and /ui console) on Modal.

    modal serve modal_app.py     # temporary URL that reloads on changes
    modal deploy modal_app.py    # permanent URL

Needs a Modal secret `apertopic-keys` with TYPESAFE_API_KEY and APERTUS_API_KEY, and optionally
APERTOPIC_PASSWORD to put the site behind a browser login (anyone with the URL otherwise spends the
API credits). The labelled data comes from ../data (see README), baked into the image.

Cost: the app mostly waits on Jev, Apertus and OpenParlData, so it runs on half a CPU and 512 MB,
scales to zero when idle, serves many requests per container and never runs more than two.
"""

from pathlib import Path

import modal

HERE = Path(__file__).parent
DATA = (HERE / "../data").resolve()

# The files the service reads at startup (about 60 MB). The large affair texts are for evaluation only.
DATA_FILES = [
    "hackapertus/aps_topics.xlsx",
    "hackapertus/che_topics_vocabulary.csv",
    "hackapertus/cantonal_keywords_vocabulary.csv",
    "hackapertus/politmonitor_digitalisierung.csv",
    "hackapertus/che_affairs_keywords.jsonl",
    "hackapertus/cantonal_affairs_keywords.jsonl",
    "exports/bodies.ndjson.gz",
]

image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_sync(uv_project_dir=str(HERE), extra_options="--no-dev")
    .env({"DATA_DIR": "/data/hackapertus", "BODIES_FILE": "/data/exports/bodies.ndjson.gz"})
)
for name in DATA_FILES:
    image = image.add_local_file(DATA / name, f"/data/{name}", copy=True)
# The package with its web console (HTML, CSS, JS), so not only the .py files.
image = image.add_local_dir(HERE / "src/parltopics", "/root/parltopics", ignore=["**/__pycache__/**"])

app = modal.App("apertopic", image=image)


@app.function(
    secrets=[modal.Secret.from_name("apertopic-keys")],
    cpu=0.5,
    memory=512,
    min_containers=0,  # nothing runs while nobody uses it
    max_containers=2,  # hard cap on parallel containers
    scaledown_window=120,  # shut down after two idle minutes
    timeout=300,
)
@modal.concurrent(max_inputs=40)
@modal.asgi_app()
def web():
    import base64
    import os
    import secrets

    from fastapi import Request
    from fastapi.responses import Response

    from parltopics.api.main import create_app

    api = create_app()
    password = os.environ.get("APERTOPIC_PASSWORD")
    if password:

        @api.middleware("http")
        async def login(request: Request, call_next):
            # Browser login: any user name, the password from the secret.
            header = request.headers.get("authorization", "")
            if header.startswith("Basic "):
                try:
                    _, _, given = base64.b64decode(header[6:]).decode().partition(":")
                except ValueError:
                    given = ""
                if secrets.compare_digest(given, password):
                    return await call_next(request)
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="aperTOPic"'})

    return api
