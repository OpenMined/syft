#!/bin/bash

set -eou pipefail

SCRIPT_DIR=$(dirname $0)
source $SCRIPT_DIR/../base.bash

SCRIPT_DATA_DIR=$SCRIPT_DIR/inputs
RING_DIR=$E2E_DIR/ring
LOGS_DIR=$RING_DIR/logs
CLIENT_DIR=$RING_DIR/client
SERVER_DIR=$RING_DIR/server
DOMAIN="openmined.org"

########## Client & Server ##########

bg_start_server() {
    local port=${1-5001}
    info "Starting server port=$port"
    export SYFTBOX_DATA_FOLDER=$SERVER_DIR
    run_bg syftbox server --port $port &> $LOGS_DIR/server.log
    unset SYFTBOX_DATA_FOLDER
}

bg_start_client() {
    local user=$1
    local port=$2
    local email="$user@$DOMAIN"

    info "Starting client email=$email port=$port"

    run_bg syftbox client \
        --config=$CLIENT_DIR/$user/config.json \
        --data-dir=$CLIENT_DIR/$user \
        --email=$email \
        --port=$port \
        --no-open-dir \
        --verbose \
        --server=http://localhost:5001 &> $LOGS_DIR/client.$1.log
}

bg_start_syftbox() {
    # start & wait for syftbox server
    bg_start_server 5001
    wait_for_server 5001

    # start & wait for syftbox clients
    bg_start_client user1 8080
    bg_start_client user2 8081
    wait_for_client 8080
    wait_for_client 8081
}

e2e_prepare_dirs() {
    rm -rf $E2E_DIR
    mkdir -p $LOGS_DIR $CLIENT_DIR
}

########## Ring ##########

path_user_datasite() {
    # get path to client's datasite
    local user=$1
    echo "$CLIENT_DIR/$user/datasites/$user@$DOMAIN"
}

path_ring_app() {
    # get path to client's ring app
    local user=$1
    echo "$CLIENT_DIR/$user/apis/ring"
}

path_ring_api_data() {
    # get path to client's ring app pipeline
    local user=$1
    echo "$(path_user_datasite $user)/api_data/ring"
}

wait_for_ring_app() {
    # wait for ring app to be be installed
    for user in $@
    do wait_for_path "$(path_ring_app $user)/run.sh" 30
    done
}

ring_copy_secrets() {
    # copy secret.json to ring app
    for user in $@
    do cp $SCRIPT_DATA_DIR/$user.secret.json "$(path_ring_app $user)/secret.json"
    done
}

ring_init() {
    # place data.json in api_data/ring/running

    local init_user="$1"
    local running="$(path_ring_api_data $init_user)/running"

    mkdir -p $running
    cp $SCRIPT_DATA_DIR/data.json $running/data.json
}

ring_wait_for_completion() {
    # wait for data.json in api_data/ring/done

    local user="$1"
    local timeout=${2:-30}
    local done="$(path_ring_api_data $user)/done"

    wait_for_path $done/data.json $timeout
}

ring_validate() {
    # validate ring results

    local user="$1"
    local eresult="$2"
    local eidx="$3"
    local done="$(path_ring_api_data $user)/done"

    # jq read data.json
    # check if "data" == 558
    local result=$(jq -r '.data' $done/data.json)
    if [ "$result" != "$eresult" ]; then
        err "Ring failed. Expected data=$eresult, got $result"
    fi

    local idx=$(jq -r '.current_index' $done/data.json)
    if [ "$idx" != "$eidx" ]; then
        err "Ring failed. Expected current_index=$eidx, got $idx"
    fi
}

start_ring() {
    # start ring workflow

    local init_user="$1"

    info "Waiting for clients to install ring app"
    wait_for_ring_app $@

    info "Copying secrets"
    ring_copy_secrets $@

    # start ring
    info "Initializing ring"
    ring_init $@

    # wait for results
    info "Waiting for ring results to be available"
    ring_wait_for_completion $init_user 120

    # check results
    info "Validating ring results"
    result=$((69 + 420 + 69))
    ring_validate $init_user $result ${#@}

    success "Ring ran successfully"
    exit 0
}

do_e2e() {
    need_cmd syftbox
    need_cmd curl
    need_cmd jq
    need_cmd just

    info "Started E2E ring"
    load_env $SCRIPT_DIR/.env

    # prepare local data directories
    e2e_prepare_dirs

    # start syftbox in background
    bg_start_syftbox

    # start ring workflow
    start_ring user1 user2

    # cleanup
    exit 0
}

do_e2e
