from flask.helpers import make_response
from rungame import create_game, extract_game, running_games
import shutil
import os
import requests
from typing import List, Literal, Union
from flask import Flask, request, render_template, redirect, session, url_for, json, jsonify, g
from flask_migrate import Migrate
from datetime import datetime as dt
from pathlib import Path
import time
import re
import msal
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from smartphone_connector import Connector
from smartphone_connector.types import DataMsg, Device
from sqlalchemy import desc, func
from dotenv import load_dotenv, find_dotenv
from msal.oauth2cli.oidc import decode_id_token
load_dotenv(find_dotenv())

root = Path(__file__).parent
app = Flask(__name__)
app.config.from_object(os.environ['APP_SETTINGS'])
# app.config['SQLALCHEMY_ECHO'] = True
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)
Session(app)


# This section is needed for url_for("foo", _external=True) to automatically
# generate http scheme when this sample is running on localhost,
# and to generate https scheme when it is deployed behind reversed proxy.
# See also https://flask.palletsprojects.com/en/1.0.x/deploying/wsgi-standalone/#proxy-setups
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)


active_clients: set = set()
active_scripts: set = set()
active_games: dict = {}
socket_conn: Connector = None

GREP_REGEX = re.compile(r'\bgrep\b')
ANONYMOUS_EMAIL = 'anonymous@foo.bar'
MAX_CONCURRENT_PLAYS = 15  # overwritten by env when present
STATUS_INTERVAL = 15    # all <STATUS_INTERVAL> seconds a get request is sent to /status
RECONNECT_INTERVAL = 15    # all <RECONNECT_INTERVAL> minutes a post request is sent to /reconnect
HAS_REPORT_REGEX = re.compile(r'\.report\(')

# important to import models AFTER initializing the app! Otherwise
# a circular import error will be thrown
from models import Game, LogMessage, Player, GamePlay, Rating


obfuscated = None


def log(type: str, msg: str, game_play_id: str = None, update_latest: bool = False):
    if update_latest:
        model = latest_log_message(type)
        if model is None:
            model = LogMessage(msg_type=type, msg=msg, game_play_id=game_play_id)
            db.session.add(model)
        model.updated_at = dt.now()
        model.msg = msg
        model.game_play_id = game_play_id
        db.session.commit()
        return
    msg = LogMessage(msg_type=type, msg=msg, game_play_id=game_play_id)
    db.session.add(msg)
    db.session.commit()
    # db.session.execute('''\
    # DELETE FROM log_messages
    # WHERE created_at < :twelve_hours_ago
    # ''', {'twelve_hours_ago': (dt.now() - timedelta(hours=12)).strftime('%Y-%m-%d %H:%M:%S')})


def get_host():
    host = os.environ.get('HOST_URL', 'http://127.0.0.1:5000/')
    while host.endswith('/'):
        host = host[:-1]
    return host


def check_gamerunner_status():
    requests.get(f'{get_host()}/status').content


sched = BackgroundScheduler(daemon=True)
sched.add_job(check_gamerunner_status, 'interval', seconds=STATUS_INTERVAL)
sched.start()
# Shutdown your cron thread if the web process is stopped
atexit.register(lambda: sched.shutdown(wait=False))


def scheduled_reconnect():
    res = requests.post(f'{get_host()}/api/v1/reconnect', json={'secret': os.environ.get('SECRET_KEY')})
    if res.ok:
        log('app:status', 'reconnected')
    else:
        log('app:status', 'failed to reconnect')


reconn_sched = BackgroundScheduler(daemon=True)
reconn_sched.add_job(scheduled_reconnect, 'interval', minutes=RECONNECT_INTERVAL)
reconn_sched.start()
# Shutdown your cron thread if the web process is stopped
atexit.register(lambda: reconn_sched.shutdown(wait=False))


@app.before_request
def load_user():
    user = None
    if not request.cookies.get('jwt'):
        user = anonymous_player()
    else:
        try:
            r = decode_id_token(request.cookies.get('jwt'))
            if 'preferred_username' in r:
                user = get_player(r['preferred_username'])
        except Exception:
            g.user = anonymous_player()

    if user is None:
        user = anonymous_player()
    g.user = user


@app.context_processor
def utility_processor():

    def obfuscated_players() -> List[str]:
        global obfuscated
        if obfuscated is None:
            raw_players = os.environ.get('OBFUSCATED_PLAYERS', '').split(';')
            sanitized = map(lambda email: email.strip(), raw_players)
            sanitized = filter(lambda email: '@' in email, sanitized)
            obfuscated = list(sanitized)

        return obfuscated

    def checked(is_checked: bool) -> str:
        if is_checked:
            return 'checked'
        return ''

    def toggle_prop(prop: str, on: bool) -> str:
        if on:
            return prop
        return ''

    def mail_of(mail: str) -> str:
        if mail in obfuscated_players():
            return 'magic.42@work.ch'
        return mail

    def mail2name(mail: str, initial_letters: Literal['both', 'last', 'first', None] = None) -> str:
        mail = mail_of(mail)
        if '@' not in mail:
            return mail
        name = mail.split('@')[0]
        if '.' not in name:
            return name
        first_name, last_name = name.split('.')
        if initial_letters == 'both':
            return f'{first_name[0]}. {last_name[0]}.'.upper()
        elif initial_letters == 'last':
            return f'{first_name.capitalize()} {last_name[0].upper()}.'
        elif initial_letters == 'first':
            return f'{first_name[0].upper()}. {last_name.capitalize()}'
        return f'{first_name.capitalize()} {last_name.capitalize()}'

    return dict(
        obfuscated_players=obfuscated_players,
        mail_of=mail_of,
        user=current_player(),
        mail2name=mail2name,
        checked=checked,
        toggle_prop=toggle_prop,
        len=len
    )


def max_concurrent_plays() -> int:
    try:
        max_plays = int(os.environ.get('MAX_CONCURRENT_PLAYS', MAX_CONCURRENT_PLAYS), base=10)
        return max_plays
    except:
        return MAX_CONCURRENT_PLAYS


def is_process_running(pid: Union[str, int]) -> bool:
    processes = os.popen(f'/bin/ps -p {pid}').read()
    return len(list(filter(lambda l: l.strip().startswith(str(pid)), processes.splitlines())))


def kill_game(device_id: str, force: bool = False, commit: bool = True):
    ps = play_session(device_id)
    home = root.joinpath('running_games')
    if not force and not home.joinpath(f'{device_id}.py').exists():
        return
    home.joinpath(f'{device_id}.kill').touch()

    if ps and not ps.end_time:
        ps.end_time = dt.now()
        if commit:
            db.session.commit()


def on_client_devices(devices: List[Device]):
    raw = filter(lambda d: d['device_id'].startswith('game-'), devices)
    raw = filter(lambda d: 'is_silent' not in d or not d['is_silent'], raw)
    clients = set(map(lambda d: d['device_id'], filter(lambda d: d['is_client'], raw)))
    scripts = set(map(lambda d: d['device_id'], filter(lambda d: not d['is_client'], raw)))
    removed_clients = active_clients - clients
    new_clients = clients - active_clients
    active_clients.update(new_clients)

    removed_scripts = active_scripts - scripts
    new_scripts = scripts - active_scripts
    active_scripts.update(new_scripts)

    for rm in removed_clients:
        log('socketio:kill', 'clientside', rm)

        if rm in active_games:
            print('alive: ', active_games[rm]['process'].is_alive())
        active_clients.remove(rm)
        kill_game(rm, commit=False)
    # stop play sessions after crash of script
    for rm in removed_scripts:
        log('socketio:kill', 'scriptside', rm)
        active_scripts.remove(rm)
        ps = play_session(rm)
        if ps and not ps.end_time:
            ps.end_time = dt.now()
    db.session.commit()


def on_highscore(data: DataMsg):
    if data.type == 'report_score':
        res = requests.post(
            f'{get_host()}/api/v1/report_score',
            json={
                'score': int(data.score),
                'game_play_id': data.device_id,
                'secret': os.environ.get('SECRET_KEY')
            }
        )
        if not res.ok:
            log('socketio:score',
                f'could not report score! {data.score}: {json.dumps(res.json())}', game_play_id=data.device_id)


def on_timer(data):
    log('socketio:timer', f'{data["time"]}', update_latest=True)


def setup(force: bool = False):
    global socket_conn
    if force and socket_conn is not None:
        socket_conn.disconnect()
    with open(root.joinpath('running'), 'w') as f:
        f.write(str(os.getpid()))
    socket_conn = Connector('https://io.gbsl.website', '__GAME_RUNNER__')
    socket_conn.on_devices = on_client_devices
    socket_conn.on_data = on_highscore
    socket_conn.on_timer = on_timer


@app.route('/')
def home():
    games = Game.ordered_by_rating()
    return render_template('home.html', active='home', games=games)


@app.route('/index')
def index():
    games = Game.ordered_by_rating()
    return render_template('index.html', games=games, active='index')


@app.route('/admin')
def admin():
    user = current_player()
    if not user.admin:
        return redirect('/')
    running = running_games()
    game_plays = db.session.execute('''\
        SELECT
            game_plays.id as id,
            game_plays.start_time as start_time,
            games.name as game,
            game_plays.player_email as player_email,
            game_plays.score as score
        FROM game_plays
            INNER JOIN games ON game_plays.game_id = games.id
        ORDER BY game_plays.start_time DESC
        LIMIT 100
    ''')
    users = Player.query.order_by(desc(Player.created_at)).all()
    return render_template('admin.html', running_games=running, active='admin', users=users, game_plays=game_plays)


@app.route('/python_logs')
def fetch_python_logs():
    user = current_player()
    if not user.admin:
        return app.response_class(response=json.dumps({}), status=200, mimetype='application/json')
    runlog = root.joinpath('run_state.log')
    if runlog.exists():
        with open(runlog, 'r') as f:
            content = f.read()
    else:
        content = 'No log found'
    response = app.response_class(
        response=json.dumps({'log': content}),
        status=200,
        mimetype='application/json'
    )
    return response


@app.route('/demo')
def demo_page():
    return render_template('demopage.html')


@app.route('/api/v1/random_game_id')
def get_random_game_id():
    limit = request.args.get('count', type=int)
    if limit is None:
        limit = 1
    result = db.session.execute('SELECT id FROM games order by random() limit :limit', {'limit': limit})
    ids = []
    for r in result:
        ids.append({'id': r['id']})
    return app.response_class(
        response=json.dumps(ids),
        status=200,
        mimetype='application/json'
    )


@app.route('/api/v1/running_games')
def fetch_running_games():
    try:
        running = running_games()
    except:
        running = []

    if len(running) > 0:
        game_play_ids = ','.join(map(lambda r: f"'{r['game_play_id']}'", running))
        result = db.session.execute(f'''\
            SELECT id, game_id, player_email
            FROM game_plays
            WHERE id IN ({game_play_ids})
        ''')
        for row in result:
            run = next(filter(lambda x: x['game_play_id'] == row['id'], running))
            run['game_id'] = row['game_id']
            run['player_email'] = row['player_email']
    response = app.response_class(
        response=json.dumps(running),
        status=200,
        mimetype='application/json'
    )
    return response


@app.route('/api/v1/reconnect', methods=['POST'])
def reconnect():
    user = current_player()
    if not user.admin:
        content = request.get_json(silent=True)
        if content is None:
            return redirect('/')
        secret = content.get('secret', 'not-secret')
        if secret != os.environ.get('SECRET_KEY'):
            return jsonify({'status': 'failed'})
        setup(force=True)
        return jsonify({'status': 'ok'})

    setup(force=True)
    return redirect('/admin')


@app.route('/api/v1/report_score', methods=['POST'])
def report_score():
    content = request.get_json(silent=True)
    if content is None:
        return jsonify({'status': 'no content'})
    secret = content.get('secret', 'not-secret')
    if secret != os.environ.get('SECRET_KEY'):
        return jsonify({'status': 'failed'})

    score = content.get('score')
    game_play_id = content.get('game_play_id')
    game_play = get_game_play(game_play_id)
    if game_play and not game_play.end_time and game_play.score < score:
        game_play.score = score
        db.session.commit()
    return jsonify({'status': 'ok'})


@app.route('/scoreboard')
def scoreboard():
    game_id = request.args.get('game_id', type=int)
    no_nav = request.args.get('no_nav')
    compact = request.args.get('compact')
    game = get_game(game_id)
    if game is None:
        return redirect('/')
    rating = db.session.execute('''\
        SELECT ROUND(avg(rating), 1) as rating, count(id) as count
        FROM ratings
        WHERE game_id = :gid
    ''', {'gid': game_id}).first()
    if rating is None:
        rating = {'rating': '', 'count': 0}

    scoreboard = db.session.execute(f'''\
        SELECT
            player_email,
            max(score) as highscore,
            count(id) as plays,
            sum(extract(epoch from (end_time-start_time))) / 60 as play_time
        FROM game_plays
        WHERE game_id = :gid AND player_email != '{ANONYMOUS_EMAIL}'
        GROUP BY player_email
        ORDER BY max(score) DESC
    ''', {'gid': game_id})
    player = current_player()
    if player.is_registered:
        my_plays = db.session.execute(f'''\
            SELECT *, extract(epoch from (end_time-start_time)) / 60 as play_time
            FROM game_plays
            WHERE game_id = :gid AND player_email = :uid
            ORDER BY start_time DESC
        ''', {'gid': game_id, 'uid': player.email})
    else:
        my_plays = None
    return render_template(
        'scoreboard.html',
        scoreboard=scoreboard,
        rating=rating,
        game=game,
        my_plays=my_plays,
        no_nav=no_nav,
        compact=compact
    )


@app.route('/most_played')
def most_played():
    result = db.session.execute('''\
        SELECT
            games.name AS name,
            games.authors AS authors,
            sum(extract(epoch from (end_time-start_time))) / 60 as duration,
            count(game_plays.id) AS count,
            avg(ratings.rating) AS rating,
            max(game_plays.score) AS max_score,
            max(extract(epoch from (end_time-start_time))) / 60 AS max_duration
        FROM games
            INNER JOIN game_plays ON games.id = game_plays.game_id
            LEFT JOIN ratings ON games.id = ratings.id
        GROUP BY games.id
        ORDER BY sum(extract(epoch from (end_time-start_time))) DESC;
    ''')
    return render_template('most_played.html', result=result, active='most_played')


@app.route('/request_player_login/<game_id>', methods=['GET'])
def request_player_login(game_id: int = -1):
    if 'flow' not in session:
        session["flow"] = _build_auth_code_flow(scopes=app.config['SCOPE'])
    playgame_id = f'game-{time.time_ns()}'
    resp = make_response(
        render_template("request_player_login.html",
                        auth_url=session["flow"]["auth_uri"], game_id=game_id, playgame_id=playgame_id)
    )
    resp.headers.set('Cache-Control', 'private, max-age=0, no-cache, no-store')
    return resp


def __play_game(game: Game, player: Player, playgame_id: str = None):
    if game is None or player is None:
        return
    if player.is_registered:
        running = player.running_games
        for run in running:
            _terminate_game(run.id)
    target = game.py_game_path
    if target is None:
        return
    device_id = start_game(target, device_id=playgame_id)
    game_play = GamePlay(
        player,
        game,
        device_id
    )
    db.session.add(game_play)
    db.session.commit()
    return device_id


@app.route('/anonym', methods=['GET'])
def game_anonym():
    game_id = request.args.get('game_id')
    playgame_id = request.args.get('playgame_id')
    if game_id is None or playgame_id is None:
        return redirect('/index')
    if get_game_play(playgame_id):
        return redirect(f'/game/{game_id}')

    game = get_game(game_id)
    player = anonymous_player()
    device_id = __play_game(game, player, playgame_id=playgame_id)
    if device_id:
        return redirect(f"https://io.gbsl.website/playground?device_id={device_id}&no_nav=true", code=302)
    else:
        return redirect('/index')


@app.route('/wait_for_start', methods=['GET'])
def wait_for_start():
    game_id = request.args.get('game_id')
    running = request.args.get('running_games')
    return render_template('wait_for_start.html', requested_game_id=game_id, running_games=running)


@app.route('/game/<game_id>', methods=['GET'])
def game(game_id: int = -1):
    game = get_game(game_id)
    if not game:
        return redirect('/index')

    player = current_player()
    if not player.is_registered:
        return redirect(f'/request_player_login/{game_id}')
    running = running_games()
    if len(running) >= max_concurrent_plays():
        return redirect(f'/wait_for_start?game_id={game_id}&running_games={len(running)}')
    device_id = __play_game(game, player)
    if device_id:
        return redirect(f"https://io.gbsl.website/playground?device_id={device_id}&no_nav=true", code=302)
    else:
        return redirect('/index')


def play_session(device_id: str) -> Union[GamePlay, None]:
    return GamePlay.query.filter(GamePlay.id == device_id).first()


def current_player() -> Player:
    return g.user


def latest_log_message(type: str) -> Union[LogMessage, None]:
    return LogMessage.query.filter(LogMessage.msg_type == type).order_by(desc(LogMessage.created_at)).first()


def anonymous_player() -> Union[Player, None]:
    player = Player.query.filter(
            Player.email == ANONYMOUS_EMAIL
    ).first()
    if player:
        return player

    player = Player(
        email=ANONYMOUS_EMAIL
    )
    db.session.add(player)
    db.session.commit()
    return player


def get_player(email: str) -> Union[Player, None]:
    return Player.query.filter(
            Player.email == email.lower()
    ).first()


def get_game(id: int) -> Union[Game, None]:
    return Game.query.filter(
            Game.id == id
    ).first()


def get_game_play(device_id: str) -> Union[GamePlay, None]:
    return GamePlay.query.filter(
            GamePlay.id == device_id
    ).first()


@app.route('/upload_game', methods=['GET', 'POST'])
def upload_game():
    user = current_player()
    # user = anonymous_player()
    if not user.is_registered:
        return redirect(url_for("login"))

    if request.method == 'POST':
        name = request.form.get('name')[:32]
        game = request.files.get('game')
        description = request.form.get('description')
        supports_acc = request.form.get('supports_acc') == 'on'
        supports_key = request.form.get('supports_key') == 'on'
        supports_gyro = request.form.get('supports_gyro') == 'on'
        supports_touch = request.form.get('supports_touch') == 'on'
        authors = request.form.get('authors')[:64]
        db_game = Game(user, name, authors,
                       description,
                       supports_acc,
                       supports_key,
                       supports_gyro,
                       supports_touch)
        db.session.add(db_game)
        db.session.commit()
        extract_game(db_game.project_path, game, db_game.preview_img)
        if request.files.get('preview'):
            if not db_game.static_folder.exists():
                db_game.static_folder.mkdir(parents=True, exist_ok=True)
            if db_game.static_folder.joinpath(db_game.preview_img).exists():
                os.remove(db_game.static_folder.joinpath(db_game.preview_img))
            preview = request.files.get('preview')
            preview.save(db_game.static_folder.joinpath(f'{db_game.preview_img}{Path(preview.filename).suffix}'))
        if db_game.py_game_path:
            with open(db_game.py_game_path, 'r') as f:
                raw = f.read()
                if not HAS_REPORT_REGEX.search(raw):
                    db_game.has_reporting = False
                    db.session.commit()
        else:
            db.session.delete(db_game)
            db.session.commit()
            return redirect('/index')
        return redirect(f'/scoreboard?game_id={db_game.id}')
    else:
        return render_template('upload_form.html', active='upload_game')


@app.route('/update_game', methods=['GET', 'POST'])
def update_game():
    user = current_player()
    if not user.is_registered:
        return redirect(url_for("login"))

    if request.method == 'POST':
        game_id = request.form.get('game_id', type=int)
        to_update = get_game(game_id)
        if not to_update:
            return redirect('/index')
        if to_update.player_email != user.email:
            if not user.admin:
                return redirect('/index')

        if to_update.name != request.form.get('name')[:32]:
            to_update.rename(request.form.get('name')[:32])
        to_update.description = request.form.get('description')
        to_update.supports_acc = request.form.get('supports_acc') == 'on'
        to_update.supports_key = request.form.get('supports_key') == 'on'
        to_update.supports_gyro = request.form.get('supports_gyro') == 'on'
        to_update.supports_touch = request.form.get('supports_touch') == 'on'
        to_update.authors = request.form.get('authors')[:64]
        game = request.files.get('game')
        if game:
            extract_game(to_update.project_path, game, to_update.preview_img)
        if request.files.get('preview'):
            if not to_update.static_folder.exists():
                to_update.static_folder.mkdir(parents=True, exist_ok=True)
            for f in to_update.static_folder.iterdir():
                if f.name.startswith(to_update.preview_img):
                    os.remove(f)
            preview = request.files.get('preview')
            preview.save(to_update.static_folder.joinpath(f'{to_update.preview_img}{Path(preview.filename).suffix}'))
        if to_update.py_game_path:
            with open(to_update.py_game_path, 'r') as f:
                raw = f.read()
                if not HAS_REPORT_REGEX.search(raw):
                    to_update.has_reporting = False
                    db.session.commit()
            db.session.commit()
        return redirect(f'/scoreboard?game_id={to_update.id}')

    else:
        game_id = request.args.get('game_id', type=int)
        to_update = get_game(game_id)
        if not to_update:
            return redirect('/index')
        if to_update.player_email != user.email:
            if not user.admin:
                return redirect('/index')

        return render_template('update_form.html', game=to_update)


@app.route('/user', methods=['GET'])
def user():
    user = current_player()
    if not user.is_registered:
        return redirect('/')
    if user.admin:
        games = Game.ordered_by_rating()
    else:
        games = user.games
    return render_template('user.html', games=games, active='user')


@app.route('/delete', methods=['POST'])
def delete():
    user = current_player()
    if not user.is_registered:
        return redirect('/')
    game_id = request.form.get('id')
    game = get_game(game_id)
    if not game:
        return redirect('/user')
    if game.player_email != user.email and not user.admin:
        return redirect('/')

    if game.project_path.exists():
        shutil.rmtree(game.project_path)
    if game.preview_img_path:
        os.remove(game.preview_img_path)
    if game.static_folder.exists() and len(list(game.static_folder.iterdir())) == 0:
        shutil.rmtree(game.static_folder)
    db.session.delete(game)
    db.session.commit()
    return redirect('/user')


def start_game(target: Path, device_id: str = None) -> str:
    global active_games
    if device_id is None:
        device_id = f'game-{time.time_ns()}'
    if device_id in active_games:
        kill_game(device_id)

    target = Path(target)
    create_game(target, device_id)
    return device_id


def _terminate_game(game_play_id: str):
    home = root.joinpath('running_games')
    if home.joinpath(f'{game_play_id}.kill').exists():
        os.remove(home.joinpath(f'{game_play_id}.kill'))
    kill_game(game_play_id, force=True)


@app.route('/game_vote', methods=['POST'])
def game_vote():
    user = current_player()
    game_id = request.form.get('game_id')
    new_rating = request.form.get('rating')
    game = get_game(game_id)
    if game is None or not user.is_registered:
        return app.response_class(status=403, response=json.dumps({'status': 'login first'}), mimetype='application/json')

    rating = user.rating(game.id)
    if rating:
        rating.rating = int(new_rating)
        db.session.commit()
    else:
        r = Rating(
            user,
            game,
            new_rating
        )
        db.session.add(r)
    db.session.commit()
    return app.response_class(status=200, response=json.dumps({'status': '200'}), mimetype='application/json')


@app.route('/status', methods=['GET'])
def status():
    timer = latest_log_message('socketio:timer')
    if timer is None:
        return app.response_class(status=400, response=json.dumps({'status': 400, 'msg': 'no timer last timer msg found'}), mimetype='application/json')

    if (dt.now() - timer.updated_at).total_seconds() > STATUS_INTERVAL:
        res = requests.post('/api/v1/reconnect', json={'secret': os.environ.get('SECRET_KEY')})
        if res.ok:
            log('app:status', 'reconnected')
        else:
            log('app:status', 'failed to reconnect')

    return jsonify({'status': 'ok'})


@app.route('/terminate_game', methods=['POST'])
def terminate_game():
    game_play_id = request.form.get('id')
    if len(str(game_play_id)) != 24 or not str(game_play_id).startswith('game-16'):
        return app.response_class(status=200, response=json.dumps({'status': 'invalid request'}), mimetype='application/json')
    user = current_player()
    if not user.is_registered:
        return app.response_class(status=200, response=json.dumps({'status': 'unauthorized'}), mimetype='application/json')
    if not user.admin:
        running = list(map(lambda proc: proc['game_play_id'], running_games()))
        if game_play_id not in running:
            return app.response_class(status=200, response=json.dumps({'status': '200'}), mimetype='application/json')
        game = user.game_play(game_play_id)
        if game is None:
            return app.response_class(status=200, response=json.dumps({'status': 'unauthorized'}), mimetype='application/json')

    _terminate_game(game_play_id)
    if request.form.get('admin_redirect', default=None):
        return redirect('/admin')
    return app.response_class(status=200, response=json.dumps({'status': '200'}), mimetype='application/json')


@app.route("/login")
def login():
    if 'flow' not in session:
        session["flow"] = _build_auth_code_flow(scopes=app.config['SCOPE'])
    return render_template("login.html", auth_url=session["flow"]["auth_uri"], active='login')


@app.route(app.config['REDIRECT_PATH'])  # Its absolute URL must match your app's redirect_uri set in AAD
def authorized():
    try:
        cache = _load_cache()
        result = _build_msal_app(cache=cache).acquire_token_by_auth_code_flow(
            session.get("flow", {}), request.args)
        if "error" in result:
            return render_template("auth_error.html", result=result)
        session["user"] = result.get("id_token_claims")
        email = session["user"]["preferred_username"].lower()
        session["user"]["preferred_username"] = email
        session["email"] = email
        exists = db.session.query(Player.email).filter_by(email=session['email']).scalar() is not None
        if not exists:
            new_player = Player(
                email=email
            )
            db.session.add(new_player)  # Adds new User record to database
            db.session.commit()  # Commits all changes
        _save_cache(cache)

        resp = make_response(redirect('/'))
        exp = result.get('id_token_claims')['exp']
        resp.set_cookie('jwt', result.get('id_token'), max_age=exp, secure=True, httponly=True, samesite='Lax')
        return resp
    except ValueError:  # Usually caused by CSRF
        pass  # Simply ignore them

    return redirect('/')


@app.route("/logout")
def logout():
    session.clear()  # Wipe out user and its token cache from session
    res = make_response(redirect('/'))
    res.set_cookie('jwt', '-', max_age=0, secure=True, httponly=True, samesite='Lax')
    return res


def _load_cache():
    cache = msal.SerializableTokenCache()
    if session.get("token_cache"):
        cache.deserialize(session["token_cache"])
    return cache


def _save_cache(cache):
    if cache.has_state_changed:
        session["token_cache"] = cache.serialize()
        root.joinpath('msal_token_cache.bin').touch(exist_ok=True)
        with open(root.joinpath('msal_token_cache.bin'), 'w') as f:
            f.write(cache.serialize())


def _build_msal_app(cache=None, authority=None):
    return msal.ConfidentialClientApplication(
        app.config['CLIENT_ID'], authority=authority or app.config['AUTHORITY'],
        client_credential=app.config['CLIENT_SECRET'], token_cache=cache)


def _build_auth_code_flow(authority=None, scopes=None):
    return _build_msal_app(authority=authority).initiate_auth_code_flow(
        scopes or [],
        redirect_uri=url_for("authorized", _external=True))


if root.joinpath('.skip_setup').exists():
    os.remove(root.joinpath('.skip_setup'))
else:
    setup()


if __name__ == '__main__':
    # Bind to PORT if defined, otherwise default to 5000.
    port = int(os.environ.get('PORT', 5000))
    app.run(host='localhost', port=port, debug=True)
