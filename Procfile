web: $(nohup /bin/bash /app/bin/on_game_state_change.sh > /home/game_runner/run_state.log 2>&1 &) && gunicorn app:app
release: (cd /app && touch .skip_setup && flask db upgrade)
