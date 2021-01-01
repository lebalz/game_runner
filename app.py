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

root = Path(__file__).parent
app = Flask(__name__)

active_clients: set = set()
active_games: dict = {}
socket_conn: Connector = None

GREP_REGEX = re.compile(r'\bgrep\b')


def is_process_running(pid: Union[str, int]) -> bool:
    processes = os.popen(f'/bin/ps -p {pid}').read()
    return len(list(filter(lambda l: l.strip().startswith(str(pid)), processes.splitlines())))


def kill_game(device_id: str):
    if not root.joinpath('running_games', f'game-{device_id}.py').exists():
        return
    root.joinpath('running_games', f'{device_id}.kill').touch()

    if device_id in active_games:
        active_games[device_id]['process'].join(5)
        if not active_games[device_id]['process'].is_alive():

            if root.joinpath('running_games', f'{device_id}.kill').exists():
                os.remove(root.joinpath('running_games', f'{device_id}.kill'))
            print(f'killed {device_id}')
            active_games[device_id]['process'].close()

            del active_games[device_id]
            file = root.joinpath('running_games', f'{device_id}.py')
            if file.exists():
                os.remove(file)
        else:
            print('could not kill process: ', device_id)


def on_client_devices(devices: List[Device]):
    print(os.getpid(), 'devices!')
    clients = set(map(lambda d: d['device_id'], filter(lambda d: d['is_client'], devices)))
    removed = active_clients - clients
    new = clients - active_clients
    active_clients.update(new)
    for rm in removed:
        print('kill', rm, active_games.keys())
        active_clients.remove(rm)
        kill_game(rm)


def setup(force: bool = False):
    global socket_conn
    print('pid: ', os.getpid())
    if root.joinpath('running').exists():
        with open(root.joinpath('running'), 'r') as f:
            current_pid = f.read().strip()
            if is_process_running(current_pid) and not force:
                return

    app.logger.info(f'connect to {__name__}')
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
        print(target_dir)
        target = next(target_dir.glob('*.py'), None)
        if target is None:
            return redirect('/index')
        target = target_dir.joinpath('game.py')
    device_id = start_game(target)
    return redirect(f"https://io.gbsl.website/playground?device_id={device_id}&no_nav=true", code=302)


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
CONNECTOR_NAME_REGEX = re.compile(r'(?P<indent>\s*)(?P<var_name>\b\S+\b)\s*=\s*Connector\(.*?\)')


def _start_game(target: str, device_id: str):
    target = Path(target)
    file = Path(__file__).parent.joinpath('running_games', f'{device_id}.py')
    shutil.copyfile(target, file)

    with open(file, 'r') as f:
        raw = f.read()
        match = CONNECTOR_NAME_REGEX.search(raw)
        if match:
            indent = match['indent']
            var_name = match['var_name']
            replacement = f'''
from pathlib import Path
import os
{indent}{var_name} = Connector("https://io.gbsl.website", "{device_id}")

def __shutdown():
    {var_name}.disconnect()
    if Path(__file__).parent.joinpath('{device_id}.kill').exists():
        os.remove(Path(__file__).parent.joinpath('{device_id}.kill'))
    exit()

def __check_running_state():
    if Path(__file__).parent.joinpath('{device_id}.kill').exists():
        __shutdown()

{var_name}.subscribe_async(__check_running_state, 1)

'''
            new_text = CONNECTOR_NAME_REGEX.sub(replacement, raw)
            cancel_subscriptions_regex = re.compile(f'(?P<indent>\s*){var_name}.cancel_async_subscriptions\(\)')
            new_text = cancel_subscriptions_regex.sub(
                f'''\
\g<indent>{var_name}.cancel_async_subscriptions()
\g<indent>{var_name}.subscribe_async(__check_running_state, 1)
''',
                new_text
            )
            with open(file, 'w') as f:
                f.write(new_text)
        else:
            return

    print('now running', file)
    if Path('venv/bin/python').exists():
        os.system(f'venv/bin/python {str(file)}')
    else:
        os.system(f'/app/.heroku/python/bin/python {str(file)}')


def start_game(target: Path) -> str:
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


setup()
if __name__ == '__main__':
    # Bind to PORT if defined, otherwise default to 5000.
    port = int(os.environ.get('PORT', 5000))
    app.run(host='localhost', port=port, debug=True)
