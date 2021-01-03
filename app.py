from rungame import create_game, game_runner, home_dir, run
import shutil
import multiprocessing as mp
import os
from typing import List, Union
from flask import Flask, request, render_template, redirect
from pathlib import Path
from zipfile import ZipFile
from datetime import datetime
import time
import re
from smartphone_connector import Connector
from smartphone_connector.types import Device
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

root = Path(__file__).parent
app = Flask(__name__)
app.config.from_object(os.environ['APP_SETTINGS'])

active_clients: set = set()
active_games: dict = {}
socket_conn: Connector = None

GREP_REGEX = re.compile(r'\bgrep\b')


def is_process_running(pid: Union[str, int]) -> bool:
    processes = os.popen(f'/bin/ps -p {pid}').read()
    return len(list(filter(lambda l: l.strip().startswith(str(pid)), processes.splitlines())))


def kill_game(device_id: str):
    home = home_dir().joinpath('.running_games')
    if not home.joinpath(f'{device_id}.py').exists():
        return
    home.joinpath(f'{device_id}.kill').touch()

    if device_id in active_games:
        active_games[device_id]['process'].join(5)
        if not active_games[device_id]['process'].is_alive():

            if home.joinpath(f'{device_id}.kill').exists():
                os.remove(home.joinpath(f'{device_id}.kill'))
            print(f'killed {device_id}')
            active_games[device_id]['process'].close()

            del active_games[device_id]
            file = home.joinpath(f'{device_id}.py')
            if file.exists():
                os.remove(file)
        else:
            print('could not kill process: ', device_id)


def on_client_devices(devices: List[Device]):
    if root.joinpath('running').exists():
        with open(root.joinpath('running'), 'r') as f:
            current_pid = f.read().strip()
            if current_pid != str(os.getpid()):
                if is_process_running(current_pid):
                    print('disconnecting from socketio server: ', os.getpid())
                    socket_conn.disconnect()
                    return
                else:
                    with open(root.joinpath('running'), 'w') as f:
                        f.write(str(os.getpid()))

    clients = set(map(lambda d: d['device_id'], filter(lambda d: d['is_client'], devices)))
    removed = active_clients - clients
    new = clients - active_clients
    active_clients.update(new)
    for rm in removed:
        print('kill', rm, active_games.keys())
        if rm in active_games:
            print('alive: ', active_games[rm]['process'].is_alive())
        active_clients.remove(rm)
        kill_game(rm)


def setup(force: bool = False):
    global socket_conn
    with open(root.joinpath('running'), 'w') as f:
        f.write(str(os.getpid()))
    socket_conn = Connector('https://io.gbsl.website', '__GAME_RUNNER__')
    socket_conn.on_devices = on_client_devices


@app.route('/')
def hello_world():
    return render_template('home.html')


@app.route('/index')
def index():
    games = list(map(lambda d: d.name, filter(
        lambda d: d.is_dir and not d.name.startswith('.'), root.joinpath('uploads').iterdir())))
    return render_template('index.html', games=games)


@app.route('/game', methods=['GET'])
def game():
    game = request.args['game']
    target_dir = Path(root.joinpath('uploads', game))
    if target_dir.joinpath('game.py').exists():
        target = target_dir.joinpath('game.py')
    else:
        target = next(target_dir.glob('*.py'), None)
        if target is None:
            return redirect('/index')
        target = target_dir.joinpath('game.py')
    device_id = start_game(target)
    return redirect(f"https://io.gbsl.website/playground?device_id={device_id}&no_nav=true", code=302)


@app.route('/upload_game', methods=['GET', 'POST'])
def upload_game():
    if request.method == 'POST':
        name = request.form.get('name')
        f = request.files.get('game')
        to = root.joinpath('uploads', f'{name}.zip')
        if root.joinpath('uploads', name).exists() and root.joinpath('uploads', name).is_dir():
            shutil.rmtree(root.joinpath('uploads', name))
        f.save(to)
        unzip(to)
        return redirect('/')
    else:
        return render_template('upload_form.html', name='FooBar')


def unzip(zip_file: Path):
    target = zip_file.parent.joinpath(zip_file.stem)
    with ZipFile(zip_file, 'r') as zip_ref:
        zip_ref.extractall(target)
    os.remove(zip_file)
    if len(list(target.glob('*.py'))) == 0:
        tmp_name = target.parent.joinpath(str(datetime.now()))
        target.rename(tmp_name)
        for item in tmp_name.iterdir():
            if item.is_dir() and not (item.name.startswith('__') or item.name.startswith('.')):
                shutil.copytree(item, target)
        shutil.rmtree(tmp_name)


def _start_game(target: str, device_id: str):
    home = home_dir().joinpath('.running_games')
    if not home.exists():
        home.mkdir(exist_ok=True)
        shutil.chown(home, user=game_runner())

    target = Path(target)
    file = create_game(target, device_id)
    if root.joinpath('venv/bin/python').exists():
        run(root.joinpath('venv/bin/python'), file, target.parent)
    else:
        run(Path('/app/.heroku/python/bin/python'), file, target.parent)


def start_game(target: Path) -> str:
    global active_games
    device_id = f'game-{time.time_ns()}'
    if device_id in active_games:
        kill_game(device_id)
    ctx = mp.get_context('spawn')
    p = ctx.Process(target=_start_game, args=(str(target), device_id))
    p.start()
    active_games[device_id] = {
        'process': p,
        'created': time.time()
    }
    return device_id


if __name__ == '__main__':
    setup()
    # Bind to PORT if defined, otherwise default to 5000.
    port = int(os.environ.get('PORT', 5000))
    app.run(host='localhost', port=port, debug=True)
