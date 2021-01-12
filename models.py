from typing import Union
from sqlalchemy import event
from app import db
from datetime import datetime as dt
from pathlib import Path
import os
import time
from werkzeug.utils import secure_filename

root = Path(__file__).parent


class Player(db.Model):
    __tablename__ = 'players'

    email = db.Column(db.String(50), primary_key=True)
    admin = db.Column(db.Boolean, index=False, unique=False, nullable=False, server_default='true', default=True)
    games = db.relationship('Game', backref='player', lazy=True)
    game_plays = db.relationship('GamePlay', backref='game_play', lazy=True)

    created = db.Column(db.DateTime, index=False, unique=False, nullable=False)

    def __init__(self, email):
        self.email = email
        self.created = dt.now()
        self.admin = False

    def __repr__(self):
        return '<email {}>'.format(self.email)

    def game_play(self, game_play_id: str):
        return db.session.execute(
            '''\
            SELECT *
            FROM game_plays
            WHERE id = :gid AND player_email = :pid
            LIMIT 1
            ''',
            {'gid': game_play_id, 'pid': self.email}
        ).first()

    def running_games(self):
        return db.session.execute(
            '''\
            SELECT *
            FROM game_plays
            WHERE player_email = :pid AND end_time IS NULL
            LIMIT 1
            ''',
            {'pid': self.email}
        )


class Game(db.Model):
    __tablename__ = 'games'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(32), index=True, unique=False, nullable=False)
    authors = db.Column(db.String(64), index=False, unique=False, nullable=False)
    created = db.Column(db.DateTime, index=False, unique=False, nullable=False)
    preview_img = db.Column(db.String(27), index=False, unique=True, nullable=False)
    player_email = db.Column(db.String(50), db.ForeignKey('players.email'), nullable=False)
    plays = db.relationship('GamePlay', backref='plays', lazy=True, cascade="all, delete")
    ratings = db.relationship('Rating', backref='ratings', lazy=True, cascade="all, delete")

    def __init__(self, player: Player, name: str, authors: str):
        self.name = name
        self.authors = authors
        self.player_email = player.email
        self.created = dt.now()
        self.preview_img = f'preview-{time.time_ns()}'

    def __repr__(self):
        return '<email {}>'.format(self.email)

    @property
    def project_path(self) -> Path:
        folder = Path(os.environ.get('UPLOAD_PATH', Path(__file__).parent.joinpath('uploads')))
        name = secure_filename(f'{self.name}-{self.id}')
        return folder.joinpath(name)

    @property
    def is_available(self) -> Path:
        return self.project_path.exists()

    @property
    def static_folder(self) -> Path:
        name = secure_filename(self.name)
        return root.joinpath('static', 'previews', name)

    @property
    def preview_img_path(self) -> Union[Path, None]:
        static_path = self.static_folder
        if not static_path.exists():
            return
        for p in static_path.iterdir():
            if p.name.startswith(self.preview_img):
                return p

    @property
    def preview_img_url(self) -> Union[str, None]:
        prev_img = self.preview_img_path
        if prev_img:
            return f'/static/previews/{prev_img.parent.name}/{prev_img.name}'


class GamePlay(db.Model):
    __tablename__ = 'game_plays'

    id = db.Column(db.String(24), primary_key=True)
    start_time = db.Column(db.DateTime, index=False, unique=False, nullable=False)
    end_time = db.Column(db.DateTime, index=False, unique=False, nullable=True)
    score = db.Column(db.Integer, index=False, unique=False, default=0)
    created = db.Column(db.DateTime, index=False, unique=False, nullable=False)

    player_email = db.Column(db.String(50), db.ForeignKey('players.email'), nullable=False)
    game_id = db.Column(db.Integer, db.ForeignKey('games.id'), nullable=False)

    def __init__(self, player: Player, game: Game, device_id: str):
        self.id = device_id
        self.player_email = player.email
        self.game_id = game.id
        self.created = dt.now()
        self.start_time = dt.now()

    def __repr__(self):
        return '<email {}>'.format(self.email)


class Rating(db.Model):
    __tablename__ = 'ratings'

    id = db.Column(db.Integer, primary_key=True)
    game_name = db.Column(db.String(32), index=True, unique=False, nullable=False)
    game_id = db.Column(db.Integer, db.ForeignKey('games.id'), nullable=False)
    created = db.Column(db.DateTime, index=False, unique=False, nullable=False)
    rating = db.Column(db.Integer, index=False, nullable=False)

    def __init__(self, player: Player, game: Game, rating: int):
        self.player_email = player.email
        self.game_id = game.id
        self.rating = rating
        self.created = dt.now()

    def __repr__(self):
        return '<email {}>'.format(self.email)
