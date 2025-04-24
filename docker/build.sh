#!/usr/bin/env bash

TAG=${1:-latest}

docker buildx build --platform linux/amd64,linux/arm64 -t "syftbox-client-jupyter:$TAG" -f docker/syftbox-client-jupyter.dockerfile .

docker buildx build --platform linux/amd64,linux/arm64 -t "syftbox-server:$TAG" -f docker/syftbox.dockerfile .
