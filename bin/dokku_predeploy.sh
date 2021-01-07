#!/bin/bash
useradd -m game_runner

# install inotify tools
apt-get update
apt-get install -y inotify-tools
touch /home/game_runner/run_state.log