from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
import random
import string
import time
from datetime import datetime, timedelta
from flask_socketio import SocketIO, emit
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import os
from os import getenv
from threading import Thread


# -------------------- App Config --------------------
app = Flask(__name__)
app.secret_key = getenv('SECRET_KEY', 'hello123')  # Use strong secret key in production

# Enable Flask-SocketIO with CORS to allow mobile access
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


# -------------------- Database Config (PostgreSQL) --------------------
DATABASE_URL = getenv(
    'DATABASE_URL',
    'postgresql+psycopg2://root:11111@127.0.0.1:5432/voting_db'
)

# Normalize "postgres://" -> "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize the database
db = SQLAlchemy(app)


# -------------------- Flask-Login --------------------
login_manager = LoginManager(app)
login_manager.login_view = 'home'


# -------------------- Models --------------------
class User(UserMixin, db.Model):
    __tablename__ = "users"   # ✅ explicitly set a safe table name

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.String(50), nullable=False)


class Idea(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    score_judge = db.Column(db.Integer, default=0)
    score_audience = db.Column(db.Integer, default=0)
    total_score = db.Column(db.Integer, default=0)


class Otp(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False)
    otp = db.Column(db.String(6), nullable=False)
    expiry_time = db.Column(db.Float, nullable=False)  # store as Unix timestamp


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ✅ Create all tables at startup (important for Render demo)
with app.app_context():
    db.create_all()


# -------------------- OTP Helpers --------------------
def generate_otp():
    return ''.join(random.choices(string.digits, k=6))  # 6-digit OTP


def send_mail(email, subject, message):
    # Demo-safe: just log OTP instead of sending
    print(f"[DEBUG] OTP for {email}: {message}")


def cleanup_otps():
    """Background task to remove expired OTPs every 5 minutes"""
    while True:
        with app.app_context():
            now = time.time()
            expired_otps = Otp.query.filter(Otp.expiry_time < now).all()
            for otp in expired_otps:
                db.session.delete(otp)
            if expired_otps:
                db.session.commit()
        time.sleep(300)

# -------------------- Routes --------------------
# (unchanged, kept same as your version)
# ...


# -------------------- Main --------------------
if __name__ == "__main__":
    # Local run
    from threading import Thread
    Thread(target=cleanup_otps, daemon=True).start()
    socketio.run(app, debug=True, port=5000, host="0.0.0.0")
else:
    # Render / Gunicorn
    from threading import Thread
    Thread(target=cleanup_otps, daemon=True).start()
    # Use Render’s assigned port
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host="0.0.0.0", port=port)