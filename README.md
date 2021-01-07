# Game Runner

A simple Flask application to upload and play [smarphone-connector](https://github.com/lebalz/smartphone-connector)/[socketio_server](https://github.com/lebalz/socketio_server) games written in python.

![game-runner](game_runner.png)

The uploaded games could have potentially unsave code - thats why the code is executed as an unprivileged user _game_runner_ with read-only access.

Whenever a python-file is added to `./running_games` (e.g. `game-1234.py`), [inotifywait](https://linux.die.net/man/1/inotifywait) starts the python script as the user _game_runner_ in a background process. When a file `name.kill` (e.g. `game-1234.kill`) is added, the previously started process is killed.

## Development

### New Migration

Since the `startup()` method should not be called on migrations, touch first the File `.skip_setup`

```sh
touch .skip_setup && flask db migrate
```

apply migration

```sh
touch .skip_setup && flask db upgrade
```

### Configure Dokku

- inotifywait is installed during the predeploy stage, @see [app.json](app.json)
- the inotify configuration can be found in [on_game_state_change.sh](on_game_state_change.sh)
- ... and is started as a background task during the startup of the flask app through the [Procfile](Procfile)

```sh
dokku config:set --no-restart game_runner APP_SETTINGS=config.ProductionConfig
```
