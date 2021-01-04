#!/bin/bash
useradd -m game_runner
mkdir /home/game_runner/.running_games
chown herokuishuser:herokuishuser /home/game_runner/.running_games

# install inotify tools
apt-get update
apt-get install -y inotify-tools
touch /home/game_runner/run_state.log