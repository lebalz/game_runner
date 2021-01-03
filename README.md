# Game Runner

A simple Flask application to upload and play [smarphone-connector](https://github.com/lebalz/smartphone-connector)/[socketio_server](https://github.com/lebalz/socketio_server) games.

## Development

run

```sh
export FLASK_APP=app
export FLASK_ENV=development
flask run
```

### Configure Dokku

```sh
dokku config:set --no-restart game_runner APP_SETTINGS=config.ProductionConfig
```
