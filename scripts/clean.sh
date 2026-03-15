#!/bin/bash

PROJECT_PATH=$(dirname -- "$(readlink -f -- "$0";)";)/..

rm -r $PROJECT_PATH/hydra-publisher/dist
rm -r $PROJECT_PATH/hydra-publisher/node_modules
rm -r $PROJECT_PATH/hydra-publisher/.angular