# A display for the window tests, for machines that have none.
#
#   docker build -f docker/gui-tests.Dockerfile -t office-agent-gui-tests .
#   docker run --rm -v "$PWD:/app" -w /app \
#       -u "$(id -u):$(id -g)" -e HOME=/tmp \
#       -e GUI_TESTS_PYTHON=/opt/venv/bin/python \
#       office-agent-gui-tests bash scripts/gui-tests.sh --no-docker
#
# `scripts/gui-tests.sh --docker` does both, and mounts the checkout so the
# tests run against the working tree rather than a copy baked into the image.

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GUI_TESTS_PYTHON=/opt/venv/bin/python

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-tk \
        xvfb \
        xauth \
        fonts-dejavu-core \
        libx11-6 \
        libxcb1 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# tkinter is a distribution package, so the virtualenv has to see the system
# packages; everything else comes from requirements.txt.
RUN python3 -m venv --system-site-packages /opt/venv

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt

RUN /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

CMD ["bash", "scripts/gui-tests.sh", "--no-docker"]
