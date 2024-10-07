# Guidelines for new commands
# - Start with a verb
# - Keep it short (max. 3 words in a command)
# - Group commands by context. Include group name in the command name.
# - Mark things private that are util functions with [private] or _var
# - Don't over-engineer, keep it simple.
# - Don't break existing commands
# - Run just --fmt --unstable after adding new commands

set dotenv-load := true

# ---------------------------------------------------------------------------------------------------------------------
# Private vars

_red := '\033[1;31m'
_cyan := '\033[1;36m'
_green := '\033[1;32m'
_yellow := '\033[1;33m'
_nc := '\033[0m'

# ---------------------------------------------------------------------------------------------------------------------
# Aliases

alias rs := run-server
alias rc := run-client
alias rj := run-jupyter
alias b := build
alias d := deploy

# ---------------------------------------------------------------------------------------------------------------------

@default:
    just --list

# ---------------------------------------------------------------------------------------------------------------------

# Run a local syftbox server on port 5001
[group('server')]
run-server port="5001" uvicorn_args="":
    uv run uvicorn syftbox.server.server:app --reload --reload-dir ./syftbox --port {{ port }} {{ uvicorn_args }}

# ---------------------------------------------------------------------------------------------------------------------

# Run a local syftbox client on any available port between 8080-9000
[group('client')]
run-client name port="auto" server="http://localhost:5001":
    #!/bin/bash
    set -eou pipefail

    # generate a local email from name, but if it looks like an email, then use it as is
    EMAIL="{{ name }}@openmined.org"
    if [[ "{{ name }}" == *@*.* ]]; then EMAIL="{{ name }}"; fi

    # if port is auto, then generate a random port between 8000-8090, else use the provided port
    PORT="{{ port }}"
    if [[ "$PORT" == "auto" ]]; then PORT=$(shuf -n 1 -i 8000-8090); fi

    # Working directory for client is .clients/<email>
    CONFIG_DIR=.clients/$EMAIL/config
    SYNC_DIR=.clients/$EMAIL/sync
    mkdir -p $CONFIG_DIR $SYNC_DIR

    echo -e "Email      : {{ _green }}$EMAIL{{ _nc }}"
    echo -e "Client     : {{ _cyan }}http://localhost:$PORT{{ _nc }}"
    echo -e "Server     : {{ _cyan }}{{ server }}{{ _nc }}"
    echo -e "Config Dir : $CONFIG_DIR"
    echo -e "Sync Dir   : $SYNC_DIR"

    uv run syftbox/client/client.py --config_path=$CONFIG_DIR/config.json --sync_folder=$SYNC_DIR --email=$EMAIL --port=$PORT --server={{ server }}

# ---------------------------------------------------------------------------------------------------------------------

# Build syftbox wheel
[group('build')]
build:
    rm -rf dist
    uv build

# Build & Deploy syftbox to a remote server using SSH
[group('build')]
deploy keyfile remote="azureuser@20.168.10.234": build
    #!/bin/bash
    set -eou pipefail

    # there will be only one wheel file in the dist directory, but you never know...
    LOCAL_WHEEL=$(ls dist/*.whl | grep syftbox | head -n 1)

    # Remote paths to copy the wheel to
    REMOTE_DIR="~"
    REMOTE_WHEEL="$REMOTE_DIR/$(basename $LOCAL_WHEEL)"

    echo -e "Deploying {{ _cyan }}$LOCAL_WHEEL{{ _nc }} to {{ _green }}{{ remote }}:$REMOTE_WHEEL{{ _nc }}"

    # change permissions to comply with ssh/scp
    chmod 600 {{ keyfile }}

    # Use scp to transfer the file to the remote server
    scp -i {{ keyfile }} "$LOCAL_WHEEL" "{{ remote }}:$REMOTE_DIR"

    # install pip package
    ssh -i {{ keyfile }} {{ remote }} "pip install --break-system-packages $REMOTE_WHEEL --force"

    # restart service
    # TODO - syftbox service was created manually on 20.168.10.234
    ssh -i {{ keyfile }} {{ remote }} "sudo systemctl daemon-reload"
    ssh -i {{ keyfile }} {{ remote }} "sudo systemctl restart syftbox"

    echo -e "{{ _green }}Deploy successful!{{ _nc }}"

# ---------------------------------------------------------------------------------------------------------------------

[group('utils')]
ssh keyfile remote="azureuser@20.168.10.234":
    ssh -i {{ keyfile }} remote

# remove all local files & directories
[group('utils')]
reset:
    # 'users' is the old directory
    rm -rf ./users ./.clients ./data ./dist *.whl

[group('utils')]
run-jupyter jupyter_args="":
    uv run \
        --with "jupyterlab" \
        --with-editable ".[dev]" \
        jupyter lab --notebook-dir=./notebooks {{ jupyter_args }}