from rungame import create_game, extract_game, running_games
import shutil
import os
from typing import List, Union
from flask import Flask, request, render_template, redirect, session, url_for, json
from flask_migrate import Migrate
from datetime import datetime as dt
from pathlib import Path
import time
import re
import msal
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from smartphone_connector import Connector
from smartphone_connector.types import DataMsg, Device
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

root = Path(__file__).parent
app = Flask(__name__)
app.config.from_object(os.environ['APP_SETTINGS'])
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
active_games: dict = {}
socket_conn: Connector = None

GREP_REGEX = re.compile(r'\bgrep\b')
ANONYMOUS_EMAIL = 'anonymous@foo.bar'

# important to import models AFTER initializing the app! Otherwise
# a circular import error will be thrown
from models import Game, Player, GamePlay


def is_process_running(pid: Union[str, int]) -> bool:
    processes = os.popen(f'/bin/ps -p {pid}').read()
    return len(list(filter(lambda l: l.strip().startswith(str(pid)), processes.splitlines())))


def kill_game(device_id: str, force: bool = False):
    ps = play_session(device_id)
    home = root.joinpath('running_games')
    if not force and not home.joinpath(f'{device_id}.py').exists():
        return
    home.joinpath(f'{device_id}.kill').touch()
    if ps and not ps.end_time:
        ps.end_time = dt.now()
        db.session.commit()


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


def on_highscore(data: DataMsg):
    if data.type == 'report_score':
        if 'device_id' not in data or 'score' not in data:
            return
        game_play = get_game_play(data.device_id)
        if not game_play:
            return
        score = int(data.score)
        if score > game_play.score:
            game_play.score = score
            db.session.commit()


def setup(force: bool = False):
    global socket_conn
    with open(root.joinpath('running'), 'w') as f:
        f.write(str(os.getpid()))
    socket_conn = Connector('https://io.gbsl.website', '__GAME_RUNNER__')
    socket_conn.on_devices = on_client_devices
    socket_conn.on_data = on_highscore


@app.route('/')
def home():
    user = current_player()
    games = Game.query.limit(18).all()
    return render_template('home.html', user=user, active='home', games=games)


@app.route('/index')
def index():
    games = Game.query.all()
    user = current_player()
    return render_template('index.html', games=games, active='index', user=user)


@app.route('/admin')
def admin():
    user = current_player()
    if not user or not user.admin:
        return redirect('/')
    running = running_games()
    return render_template('admin.html', running_games=running, active='admin', user=user, users=Player.query.all())


@app.route('/running_games')
def fetch_running_games():
    user = current_player()
    if not user or not user.admin:
        return app.response_class(response=json.dumps({}), status=200, mimetype='application/json')
    running = running_games()
    response = app.response_class(
        response=json.dumps(running),
        status=200,
        mimetype='application/json'
    )
    return response


@app.route('/scoreboard/<game_id>')
def scoreboard(game_id: int = -1):
    game = get_game(game_id)
    rating = db.session.execute('''\
        SELECT avg(rating) as rating, count(id) as count
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
    return render_template('scoreboard.html', scoreboard=scoreboard, rating=rating, game=game, user=current_player())


@ app.route('/terminate_game', methods=['POST'])
def terminate_game():
    user = current_player()
    if not user or not user.admin:
        return redirect('/')
    game_play_id = request.form.get('id')
    home = root.joinpath('running_games')
    if home.joinpath(f'{game_play_id}.kill').exists():
        os.remove(home.joinpath(f'{game_play_id}.kill'))
    kill_game(game_play_id, force=True)
    time.sleep(0.5)
    return redirect('/admin')


@ app.route('/most_played')
def most_played():
    result = db.session.execute('''\
        SELECT
            games.name AS "name",
            games.authors AS "authors",
            sum(game_plays.end_time-game_plays.start_time) AS "duration",
            count(game_plays.id) AS "count",
            avg(ratings.rating) AS "rating",
            max(game_plays.score) AS "max_score",
            max(game_plays.end_time-game_plays.start_time) AS "max_duration"
        FROM games
            INNER JOIN game_plays ON games.id = game_plays.game_id
            LEFT JOIN ratings ON games.id = ratings.id
        GROUP BY games.id
        ORDER BY sum(game_plays.end_time-game_plays.start_time) DESC;
    ''')
    return render_template('most_played.html', result=result, active='most_played', user=current_player())


@ app.route('/request_player_login', methods=['GET'])
def request_player_login():
    game = request.args['game']
    if 'flow' not in session:
        session["flow"] = _build_auth_code_flow(scopes=app.config['SCOPE'])
    return render_template("request_player_login.html", auth_url=session["flow"]["auth_uri"], game=game)


@ app.route('/game/<game_id>', methods=['GET'])
def game(game_id: int = -1):
    game = get_game(game_id)
    if not game:
        return redirect('/index')

    email = session.get("email")
    if 'anonymous' in request.args:
        player = anonymous_player()
    elif not email:
        return redirect(f'/request_player_login?game={game_id}')
    else:
        player = current_player()

    if not player:
        return redirect('/index')

    target_dir = game.project_path
    if target_dir.joinpath('game.py').exists():
        target = target_dir.joinpath('game.py')
    else:
        target = next(target_dir.glob('*.py'), None)
        if target is None:
            return redirect('/index')
    device_id = start_game(target)
    game_play = GamePlay(
        player,
        game,
        device_id
    )
    db.session.add(game_play)
    db.session.commit()
    return redirect(f"https://io.gbsl.website/playground?device_id={device_id}&no_nav=true", code=302)


def play_session(device_id: str) -> Union[GamePlay, None]:
    return GamePlay.query.filter(GamePlay.id == device_id).first()


def current_player() -> Union[Player, None]:
    email = session.get('email')
    if not email:
        return None
    return Player.query.filter(
            Player.email == email
    ).first()


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


def get_game(id: int) -> Union[Game, None]:
    return Game.query.filter(
            Game.id == id
    ).first()


def get_game_play(device_id: str) -> Union[GamePlay, None]:
    return GamePlay.query.filter(
            GamePlay.id == device_id
    ).first()


@ app.route('/upload_game', methods=['GET', 'POST'])
def upload_game():
    user = current_player()
    if not user:
        return redirect(url_for("login"))

    if request.method == 'POST':
        player = current_player()
        name = request.form.get('name')[:32]
        game = request.files.get('game')
        authors = request.form.get('authors')[:64]
        db_game = Game(player, name, authors)
        db.session.add(db_game)
        db.session.commit()
        extract_game(db_game.project_path, game, db_game.preview_img)
        return redirect('/index')
    else:
        return render_template('upload_form.html', active='upload_game', user=user)


@ app.route('/user', methods=['GET'])
def user():
    user = current_player()
    return render_template('user.html', games=user.games, active='user', user=user)


@ app.route('/delete', methods=['POST'])
def delete():
    user = current_player()
    if not user:
        return redirect('/')
    game_id = request.form.get('id')
    game = get_game(game_id)
    if not game:
        return redirect('/user')
    if game.player_email != user.email:
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


def start_game(target: Path) -> str:
    global active_games
    device_id = f'game-{time.time_ns()}'
    if device_id in active_games:
        kill_game(device_id)

    target = Path(target)
    create_game(target, device_id)
    return device_id


@ app.route("/login")
def login():
    if 'flow' not in session:
        session["flow"] = _build_auth_code_flow(scopes=app.config['SCOPE'])
    return render_template("login.html", auth_url=session["flow"]["auth_uri"], active='login')


@ app.route(app.config['REDIRECT_PATH'])  # Its absolute URL must match your app's redirect_uri set in AAD
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
    except ValueError:  # Usually caused by CSRF
        pass  # Simply ignore them
    return redirect('/')


@ app.route("/logout")
def logout():
    session.clear()  # Wipe out user and its token cache from session
    return redirect(  # Also logout from your tenant's web session
        app.config['AUTHORITY'] + "/oauth2/v2.0/logout" +
        "?post_logout_redirect_uri=" + url_for("index", _external=True))


def _load_cache():
    cache = msal.SerializableTokenCache()
    if session.get("token_cache"):
        cache.deserialize(session["token_cache"])
    return cache


def _save_cache(cache):
    if cache.has_state_changed:
        session["token_cache"] = cache.serialize()


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
