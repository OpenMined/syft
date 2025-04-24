FROM cgr.dev/chainguard/wolfi-base

ARG PYTHON_VERSION="3.12"
ARG UV_VERSION="0.4.20-r0"
ARG SYFT_VERSION="0.4.0"

RUN apk update && apk upgrade && apk add --no-cache python-$PYTHON_VERSION uv=$UV_VERSION

WORKDIR /app

RUN uv venv

COPY ./syftbox ./syftbox
COPY pyproject.toml .
COPY README.md .
COPY ./scripts/syftbox_client_jupyter_entrypoint.sh ./start.sh
RUN chmod +x ./start.sh

RUN uv pip install .
RUN uv pip install jupyter
RUN mkdir ~/SyftBox

EXPOSE 8000
EXPOSE 8888

ENTRYPOINT [ "./start.sh" ]
