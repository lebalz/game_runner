#!/usr/bin/env python

import re
import pwd
import os
from pathlib import Path
import time
from typing import Any
from zipfile import ZipFile
import shutil
from datetime import datetime as dt


CONNECTOR_REGEX = re.compile(r'Connector\(.*?\)')
CONNECTOR_NAME_REGEX = re.compile(r'(?P<indent>\s*)(?P<var_name>\b\S+\b)\s*=\s*Connector\(.*?\)')

RUNNING_GAME_REGEX = re.compile(
    r'^(?P<pid>\d+).*?/app/\.heroku/python/bin/python3 /app/running_games/(?P<game>game-\d{19})\.py$')

DEFAULT_GAME_RUNNER = 'game_runner'
root = Path(__file__).parent


def game_runner() -> str:
    return os.getenv('GAME_RUNNER', DEFAULT_GAME_RUNNER)


def game_runner_home() -> Path:
    name = os.getenv('GAME_RUNNER', DEFAULT_GAME_RUNNER)
    pw = pwd.getpwnam(name)
    return Path(pw.pw_dir)


def running_games():
    raw_processes = map(lambda p: p.strip(), os.popen(f'/bin/ps a -u game_runner').read().splitlines())
    processes = map(lambda proc: RUNNING_GAME_REGEX.match(proc), raw_processes)
    processes = filter(lambda proc: proc is not None, processes)
    running = list(map(lambda proc: {'pid': proc['pid'], 'game_play_id': proc['game']}, processes))
    return running


def upload_dir() -> Path:
    return os.environ.get('UPLOAD_PATH', Path(__file__).parent.joinpath('uploads'))


def unzip(zip_file: Path, preview_name: str):
    target = zip_file.parent.joinpath(zip_file.stem)
    with ZipFile(zip_file, 'r') as zip_ref:
        zip_ref.extractall(target)
    os.remove(zip_file)
    if len(list(target.glob('*.py'))) == 0:
        tmp_name = target.parent.joinpath(f'tmp-{time.time_ns()}')
        first_folder = None
        for item in target.iterdir():
            if first_folder is None and item.is_dir() and not (item.name.startswith('__') or item.name.startswith('.')):
                first_folder = item
        if first_folder:
            shutil.copytree(first_folder, tmp_name)
            shutil.rmtree(target)
            tmp_name.rename(target)
    if target.exists() and target.is_dir():
        project_name = '-'.join(target.stem.split('-')[:-1])
        if len(project_name) == 0:
            project_name = target.stem
        static_dir = root.joinpath('static', 'previews', project_name)
        # look for preview image
        for img in target.iterdir():
            if img.stem.startswith('preview'):
                static_dir.mkdir(exist_ok=True)
                shutil.move(img, static_dir.joinpath(f'{preview_name}{img.suffix}'))
                return


def extract_game(project_path: Path, game: Any, preview_name: str):
    '''
    Parameters
    ----------
    project_path : Path

    game : file from multipart form
        e.g. request.files.get('game')
    '''
    is_zip = game.filename.endswith('.zip')
    if is_zip:
        if project_path.exists() and project_path.is_dir():
            shutil.rmtree(project_path)
        to = project_path.parent.joinpath(f'{project_path.name}.zip')
        game.save(to)
        unzip(to, preview_name)
    else:
        to = project_path.joinpath(game.filename)
        project_path.mkdir(exist_ok=True)
        # remove all existing python files
        for f in project_path.iterdir():
            if f.name.endswith('.py') and f.is_file():
                os.remove(f)

        game.save(to)


def create_game(target: Path, device_id: str) -> Path:
    file = root.joinpath('running_games', f'{device_id}.py')
    with open(target, 'r') as f:
        raw = f.read()
    with open(root.joinpath('running_games', f'{device_id}.project'), 'w') as f:
        f.write(target.parent.name)

    match = CONNECTOR_NAME_REGEX.search(raw)
    if match:
        var_name = match['var_name']
        replacement = f'''
\g<indent>from pathlib import Path
\g<indent>import os
\g<indent>with open('/home/{game_runner()}/{device_id}.kill.pid', 'w') as f:
\g<indent>    f.write(str(os.getpid()))
\g<indent>{var_name} = Connector("https://io.gbsl.website", "{device_id}")
\g<indent>{var_name}.sleep(0.2) # add some time to connect in case of an error later in the script
\g<indent>def __shutdown():
\g<indent>    {var_name}.disconnect()
\g<indent>    exit()
\g<indent>
\g<indent>def __check_running_state():
\g<indent>    try:
\g<indent>        if Path(__file__).parent.joinpath('{device_id}.kill').exists():
\g<indent>            __shutdown()
\g<indent>    except:
\g<indent>        __shutdown()

\g<indent>{var_name}.subscribe_async(__check_running_state, 1)

'''
        new_text = CONNECTOR_NAME_REGEX.sub(replacement, raw)
        cancel_subscriptions_regex = re.compile(f'(?P<indent>\s*){var_name}.cancel_async_subscriptions\(\)')

        # \g<intdent> directly capture&inserts the matched ?P<indent>
        new_text = cancel_subscriptions_regex.sub(
            f'''\
\g<indent>{var_name}.cancel_async_subscriptions()
\g<indent>{var_name}.subscribe_async(__check_running_state, 1)
''',
            new_text
        )
        if not var_name.startswith('self.'):
            new_text = f'{new_text}\n\n{var_name}.wait()'
        with open(file, 'w') as f:
            f.write(new_text)
    else:
        return

    return file
