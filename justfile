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

[group('build')]
fetch-syftbox-version version="latest":
    #!/bin/bash
    set -euo pipefail

    # If version is latest, then fetch the latest version from PyPI
    # else, check if the version exists on PyPI
    if [ "{{ version }}" = "latest" ]; then
        echo "Fetching the latest version of syftbox from PyPI..."
        curl -sSf "https://pypi.org/pypi/syftbox/json" | jq -r ".info.version" || { echo "Failed to fetch the latest version." >&2; exit 1; }
    else
        echo "Checking if syftbox version {{ version }} exists on PyPI..."
        if curl -sSf -o /dev/null "https://pypi.org/pypi/syftbox/{{ version }}/json"; then
            echo "{{ version }}"
        else
            echo "syftbox version {{ version }} does not exist." >&2
            exit 1
        fi
    fi


# Build & Deploy syftbox to a remote server using SSH
[group('build')]
deploy keyfile version="latest" remote="azureuser@20.168.10.234":
    #!/bin/bash
    set -eou pipefail

    # change permissions to comply with ssh/scp
    chmod 600 {{ keyfile }}

    # Sanity Check the syft box version
    REMOTE_VERSION=$(just fetch-syftbox-version {{ version }} | tail -n 1)

    echo -e "Deploying syftbox version $REMOTE_VERSION to {{ remote }}..."

    # install pip package
    ssh -i {{ keyfile }} {{ remote }} "pip install syftbox==$REMOTE_VERSION --break-system-packages  --force"

    # restart service
    # TODO - syftbox service was created manually on 20.168.10.234
    ssh -i {{ keyfile }} {{ remote }} "sudo systemctl daemon-reload"
    ssh -i {{ keyfile }} {{ remote }} "sudo systemctl restart syftbox"

    echo -e "{{ _green }}Deploy successful!{{ _nc }}"

# Bump version, commit and tag
[group('build')]
bump-version level="patch":
    #!/bin/bash
    # We need to uv.lock before we can commit the whole thing in the repo.
    # DO not bump the version on the uv.lock file, else other packages with same version might get updated

    set -eou pipefail

    # sync dev dependencies for bump2version
    uv sync --frozen

    # get the current and new version
    BUMPVERS_CHANGES=$(uv run bump2version --dry-run --allow-dirty --list {{ level }})
    CURRENT_VERSION=$(echo "$BUMPVERS_CHANGES" | grep current_version | cut -d'=' -f2)
    NEW_VERSION=$(echo "$BUMPVERS_CHANGES" | grep new_version | cut -d'=' -f2)
    echo "Bumping version from $CURRENT_VERSION to $NEW_VERSION"

    # first bump version
    uv run bump2version {{ level }}

    # update uv.lock file to reflect new package version
    uv lock

    # commit the changes
    git commit -am "Bump version $CURRENT_VERSION -> $NEW_VERSION"
    git tag -a $NEW_VERSION -m "Release $NEW_VERSION"

# ---------------------------------------------------------------------------------------------------------------------

[group('utils')]
ssh keyfile remote="azureuser@20.168.10.234":
    ssh -i {{ keyfile }} {{ remote }}    

# remove all local files & directories
[group('utils')]
reset:
    # 'users' is the old directory
    rm -rf ./users ./.clients ./data ./dist *.whl

[group('utils')]
run-jupyter jupyter_args="":
    uv run --frozen --with "jupyterlab" \
        jupyter lab {{ jupyter_args }}
