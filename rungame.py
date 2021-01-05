#!/usr/bin/env python

import re
import pwd
import os
from pathlib import Path


CONNECTOR_REGEX = re.compile(r'Connector\(.*?\)')
CONNECTOR_NAME_REGEX = re.compile(r'(?P<indent>\s*)(?P<var_name>\b\S+\b)\s*=\s*Connector\(.*?\)')

DEFAULT_GAME_RUNNER = 'game_runner'
DEFAULT_GAME_RUNNER_PW = 'asdfasdf'


def game_runner() -> str:
    return os.getenv('GAME_RUNNER', DEFAULT_GAME_RUNNER)


def home_dir() -> Path:
    name = os.getenv('GAME_RUNNER', DEFAULT_GAME_RUNNER)
    try:
        pwd.getpwnam(name)
    except KeyError:
        game_runner_pw = os.getenv('GAME_RUNNER_PW', DEFAULT_GAME_RUNNER_PW)
        os.system(f'useradd -m {name} -p {game_runner_pw}')
    pw = pwd.getpwnam(name)
    return Path(pw.pw_dir)


def create_game(target: Path, device_id: str) -> Path:
    home = home_dir()
    file = home.joinpath('.running_games', f'{device_id}.py')
    with open(target, 'r') as f:
        raw = f.read()
    with open(home.joinpath('.running_games', f'{device_id}.project'), 'w') as f:
        f.write(target.parent.name)

    match = CONNECTOR_NAME_REGEX.search(raw)
    if match:
        indent = match['indent']
        var_name = match['var_name']
        replacement = f'''
from pathlib import Path
import os
with open('/home/{game_runner()}/{device_id}.kill.pid', 'w') as f:
    f.write(str(os.getpid()))
{indent}{var_name} = Connector("https://io.gbsl.website", "{device_id}")

def __shutdown():
    {var_name}.disconnect()
    exit()

def __check_running_state():
    try:
        if Path(__file__).parent.joinpath('{device_id}.kill').exists():
            __shutdown()
    except:
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

    return file
