#!/bin/sh
set -eu
NAMESPACE="${DEFAULT_NAMESPACE:-default}"
ADDRESS="${TEMPORAL_ADDRESS:-temporal:7233}"
echo "Waiting for Temporal at ${ADDRESS}..."
until temporal operator cluster health --address "$ADDRESS" >/dev/null 2>&1; do sleep 3; done
if temporal operator namespace describe -n "$NAMESPACE" --address "$ADDRESS" >/dev/null 2>&1; then
  echo "Namespace '$NAMESPACE' already exists"
else
  temporal operator namespace create -n "$NAMESPACE" --retention 7d --address "$ADDRESS"
  echo "Namespace '$NAMESPACE' created"
fi
