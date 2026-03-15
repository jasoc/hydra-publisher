#!/bin/bash

PROJECT_PATH=$(dirname -- "$(readlink -f -- "$0";)";)/../hydra-publisher

main()
{
    cd $PROJECT_PATH
    if [ ! -d "node_modules" ]; then
        yarn install
    fi
    yarn tauri dev
}

main "$@"
