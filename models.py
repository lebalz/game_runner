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
    games = db.relationship('Game', backref='players', lazy=True)
    game_plays = db.relationship('GamePlay', backref='game_plays', lazy=False)
    ratings = db.relationship('Rating', backref='players', lazy=False)

    created = db.Column(db.DateTime, index=False, unique=False, nullable=False)

    def __init__(self, email):
        self.email = email
        self.created = dt.now()
        self.admin = False

    def __repr__(self):
        return '<email {}>'.format(self.email)

    def can_rate(self, game_id: int) -> bool:
        res = next(filter(lambda p: p.game_id == game_id and p.time_played > 5, self.game_plays), None)
        return res is not None

    def rating_score(self, game_id: int) -> Union[int, None]:
        res = self.rating(game_id)
        return res.rating if res is not None else None

    def rating(self, game_id: int):
        return next(filter(lambda r: r.game_id == game_id, self.ratings), None)

    def is_registered(self) -> bool:
        return self.email != 'anonymous@foo.bar'

    def game_play(self, game_play_id: str):
        return next(
            filter(
                lambda p: p.id == game_play_id,
                self.game_plays
            ),
            None
        )

    @property
    def running_games(self):
        return list(
            filter(
                lambda p: p.is_running,
                self.game_plays
            )
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
    ratings = db.relationship('Rating', backref='ratings', lazy=False, cascade="all, delete")

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
    def num_ratings(self) -> int:
        return len(self.ratings)

    @property
    def rating(self) -> Union[float, None]:
        num = self.num_ratings
        if num is None:
            return None
        return sum(map(lambda r: r.rating, self.ratings)) / self.num_ratings

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

    @property
    def is_running(self) -> bool:
        return self.end_time is None

    @property
    def time_played(self) -> float:
        '''played time in seconds
        '''
        if self.end_time is None:
            return 0
        return (self.end_time - self.start_time).total_seconds()


class Rating(db.Model):
    __tablename__ = 'ratings'

    id = db.Column(db.Integer, primary_key=True)
    player_email = db.Column(db.String(50), db.ForeignKey('players.email'), nullable=False)
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
