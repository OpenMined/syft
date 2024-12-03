#!/bin/bash

PWD=$(pwd)
E2E_DIR=$PWD/.e2e

reset='\033[0m'
boldwhite='\033[1;37m'
red='\033[1;31m'
green='\033[1;32m'
yellow='\033[0;33m'
blue='\033[0;34m'
magenta='\033[0;35m'
boldcyan='\033[1;36m'

pids=( )

########## Logging ##########

err() {
    echo -e "${red}ERROR: ${boldwhite}$1${reset}" >&2
    exit 1
}

info() {
    echo -e "${boldcyan}$1${reset}"
}

warn() {
    echo -e "${yellow}$1${reset}"
}

debug() {
    echo -e "${blue}$1${reset}"
}

success() {
    echo -e "${green}$1${reset}"
}

check_cmd() {
    command -v "$1" > /dev/null 2>&1
    return $?
}

need_cmd() {
    if ! check_cmd "$1"
    then err "need '$1' (command not found)"
    fi
}

########## Concurrent processes management ##########

cleanup() {
    for pid in "${pids[@]}"
    do
        # if the process is still running, kill it
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || echo "Failed to kill $pid"
        fi
    done
}

trap cleanup SIGINT EXIT TERM

run_bg() {
    "$@" & # Run the command in background
    pids+=($!) # Store the pid
}


########## Path helpers ##########

wait_for_path() {
    local path="$1"
    local timeout=${2:-30}  # Default 30s timeout
    local interval=${3:-1}  # Default 1s polling interval
    local start_time=$(date +%s)

    debug "Waiting for: $path timeout=${timeout}s"

    while [ ! -e "$path" ]; do
        elapsed=$(($(date +%s) - start_time))

        if [ $elapsed -ge $timeout ]; then
            err "Timeout after ${timeout}s waiting for: $path"
            return 1
        fi
        sleep $interval
    done

    debug "Found: $path (after ${elapsed}s)"
    return 0
}

########## URL helpers ##########

wait_for_url() {
    local url="$1"
    local timeout=${2:-30}
    local interval=${3:-1}  # Default 1s polling interval
    local start_time=$(date +%s)

    curl -sf \
        --retry 100 --retry-all-errors \
        --retry-delay 1 --retry-max-time $timeout \
        $url > /dev/null

    if [ $? -ne 0 ]; then
        err "Failed to get response from $url"
    fi

    elapsed=$(($(date +%s) - start_time))
    debug "Got response from $url (after ${elapsed}s)"
}

wait_for_server() {
    local port=${1-8080}
    local timeout=${2:-30}

    debug "Waiting for server to be read on port=$port"
    wait_for_url "http://localhost:$port/info" $timeout
}

wait_for_client() {
    local port=${1-8080}
    local timeout=${2:-30}

    debug "Waiting for client to be ready on port=$port"
    wait_for_url "http://localhost:$port/datasites" $timeout
}

########## env helpers ##########

load_env() {
    local env_file="$1"
    if [ -f "$env_file" ]; then
        export $(grep -v '^#' "$env_file" | xargs)
    fi
}
