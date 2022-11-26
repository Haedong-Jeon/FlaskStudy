from datetime import datetime, timedelta

import jwt
from flask import Flask, jsonify, request, g, current_app
from flask.json import JSONEncoder
from sqlalchemy import create_engine, text
import bcrypt
from functools import wraps


def create_app(test_config=None):
    app = Flask(__name__)
    app.users = {}
    app.id_count = 1
    app.tweets = []

    if test_config is None:
        app.config.from_pyfile("config.py")
    else:
        app.config.update(test_config)
    database = create_engine(app.config['DB_URL'], encoding='utf-8', max_overflow=0)
    app.database = database
    app.json_encoder = CustomJSONEncoder

    @app.route("/sign-up", methods=["POST"])
    def sign_up():
        new_user = request.json
        new_user["password"] = bcrypt.hashpw(
            new_user["password"].encode("UTF-8"),
            bcrypt.gensalt()
        )
        new_user_id = app.database.execute(text("""
        INSERT INTO users (
            name,
            email,
            profile,
            hashed_password
        ) VALUES (
            :name,
            :email,
            :profile,
            :password
        )
        """), new_user).lastrowid

        row = app.database.execute(text("""
        SELECT
            id,
            name,
            email,
            profile
        FROM users
        WHERE id = :user_id
        """), {
            'user_id': new_user_id
        }).fetchone()

        created_user = {
            'id': row['id'],
            'name': row['name'],
            'email': row['email'],
            'profile': row['profile']
        } if row else None

        return jsonify(created_user)

    @app.route("/login", methods=["POST"])
    def login():
        credential = request.json
        email = credential['email']
        password = credential['password']
        row = database.execute(text("""
        SELECT
            id,
            hashed_password
        FROM users
        WHERE email = :email
        """), {'email': email}).fetchone()

        if row and bcrypt.checkpw(password.encode('UTF-8'), row['hashed_password'].encode('UTF-8')):
            user_id = row['id']
            payload = {
                'user_id': user_id,
                'exp': datetime.utcnow() + timedelta(seconds=60 * 60 * 24)
            }
            token = jwt.encode(payload, app.config['JWT_SECRET_KEY'], 'HS256')
            return jsonify({"access_token": token.decode("UTF-8")})
        else:
            return "", 401

    @app.route("/tweet", methods=["POST"])
    @login_required
    def tweet():
        user_tweet = request.json
        tweet = user_tweet["tweet"]
        if len(tweet) > 300:
            return "300자 초과", 400
        app.database.execute(text("""
        INSERT INTO tweets(
            user_id,
            tweet
        ) VALUES (
            :id,
            :tweet
        )
        """), user_tweet)
        return "", 200

    @app.route("/timeline/<int:user_id>", methods=["GET"])
    @login_required
    def timeline(user_id):
        rows = app.database.execute(text("""
        SELECT
            t.user_id,
            t.tweet
        FROM tweets t
        LEFT JOIN users_follow_list ufl ON t.user_id = :user_id
        OR (t.user_id = ufl.follow_user_id AND ufl.user_id = :user_id)
        """), {
            'user_id': user_id
        }).fetchall()
        timeline = [{
            'user_id': row['user_id'],
            'tweet': row['tweet']
        } for row in rows]
        return jsonify({
            "user_id": user_id,
            "timeline": timeline
        })

    return app


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        access_token = request.headers.get("Authorization")
        if access_token is not None:
            try:
                payload = jwt.decode(access_token, current_app.config['JWT_SECRET_KEY'], 'HS256')
            except jwt.InvalidTokenError:
                payload = None

            if payload is None:
                return 401

            user_id = payload['user_id']
            g.user_id = user_id
            # g.user = get_user_info(user_id) if user_id else None
        else:
            return 401
        return f(*args, **kwargs)

    return decorated_function


class CustomJSONEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, set):  # isinstance(a,type) → a가 type인지 확인하는 함수. 이 경우, obj가 set인지 확인
            return list(obj)
        return JSONEncoder.default(self, obj)
