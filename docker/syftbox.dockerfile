ARG PYTHON_VERSION="3.12"
ARG UV_VERSION="0.4.20-r0"

# ==================== [BUILD STEP] Python Dev Base ==================== #

FROM cgr.dev/chainguard/wolfi-base AS syft_deps

ARG PYTHON_VERSION
ARG UV_VERSION

# Setup Python DEV
RUN apk update && apk upgrade && \
    apk add build-base gcc python-$PYTHON_VERSION-dev uv=$UV_VERSION && \
    # preemptive fix for wolfi-os breaking python entrypoint
    (test -f /usr/bin/python || ln -s /usr/bin/python3.12 /usr/bin/python)

ENV UV_HTTP_TIMEOUT=600

# Set the working directory inside the container
WORKDIR /app
COPY . /app

RUN uv venv .venv
RUN uv pip install -e .

CMD ["ash", "/app/scripts/server.sh"]

