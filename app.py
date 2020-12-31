import shutil
import multiprocessing as mp
import os
from typing import List
from flask import Flask, request, render_template, redirect
from pathlib import Path
from zipfile import ZipFile
from datetime import datetime
import time
import re
from smartphone_connector import Connector
from smartphone_connector.types import Device

root = Path(__file__).parent
app = Flask(__name__)

active_clients: set = set()
active_games: dict = {}


def on_client_devices(devices: List[Device]):
    clients = set(map(lambda d: d['device_id'], filter(lambda d: d['is_client'], devices)))
    removed = active_clients - clients
    new = clients - active_clients
    active_clients.update(new)
    for rm in removed:
        active_clients.remove(rm)
        if rm in active_games:
            processes = os.popen(f'/bin/ps ax | grep {rm}.py').read()
            for process in processes.splitlines():
                pid = process.strip().split(' ')[0]
                if pid:
                    print(f'/bin/kill -9 {pid}')
                    os.system(f'/bin/kill -9 {pid}')
            del active_games[rm]
            file = root.joinpath('running_games', f'{rm}.py')
            os.remove(file)


app.logger.info(f'connect to {__name__}')
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
        print(target_dir)
        target = next(target_dir.glob('*.py'), None)
        if target is None:
            return redirect('/index')
        target = target_dir.joinpath('game.py')
    device_id = start_game(target)
    return render_template('game.html', device_id=device_id)


@app.route('/upload_game', methods=['GET', 'POST'])
def upload_game():
    print(request.form.get('name'))
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


CONNECTOR_REGEX = re.compile(r'Connector\(.*?\)')


def _start_game(target: str, device_id: str, debug: bool = False):
    target = Path(target)
    file = Path(__file__).parent.joinpath('running_games', f'{device_id}.py')
    shutil.copyfile(target, file)

    with open(file, 'r') as f:
        new_text = CONNECTOR_REGEX.sub(f'Connector("https://io.gbsl.website", "{device_id}")', f.read())
    print('\n'.join(new_text.splitlines()[:10]))
    with open(file, 'w') as f:
        f.write(new_text)

    print('now running', file)
    if debug:
        os.system(f'venv/bin/python {str(file)}')
    else:
        os.system(f'/app/.heroku/python/bin/python {str(file)}')


def start_game(target: Path) -> str:
    device_id = f'game-{time.time_ns()}'
    if device_id in active_games:
        active_games[device_id].kill()
    ctx = mp.get_context('spawn')
    p = ctx.Process(target=_start_game, args=(str(target), device_id, app.debug))
    p.start()
    active_games[device_id] = p
    return device_id


if __name__ == '__main__':
    # Bind to PORT if defined, otherwise default to 5000.
    port = int(os.environ.get('PORT', 3000))
    app.run(host='localhost', port=port, debug=True)
