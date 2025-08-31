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

with app.app_context():
    db.create_all()



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
@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        email = request.form['email']
        role = request.form['role']
        user = User.query.filter_by(email=email, role=role).first()
        if user:
            login_user(user)
            session.permanent = True
            return redirect(url_for(f'{role}_dashboard'))
        flash("Invalid email or role.", "danger")
    return render_template('login.html')


@app.route('/send_otp', methods=['POST'])
def send_otp():
    email = request.form['email']
    role = request.form['role']

    if not email.endswith('@amdocs.com'):
        flash("Only @amdocs.com email addresses are allowed!", "danger")
        return redirect(url_for('home'))

    user = User.query.filter_by(email=email).first()

    if role in ["judge", "admin"]:
        if not user:
            flash("Email not registered!", "danger")
            return redirect(url_for('home'))
        if user.role != role:
            flash("Role mismatch. Please choose the correct role.", "danger")
            return redirect(url_for('home'))

    if role == "audience" and not user:
        user = User(email=email, role=role)
        db.session.add(user)
        db.session.commit()

    # Generate OTP
    otp = generate_otp()
    expiry_time = time.time() + 900  # 15 min

    # Remove old OTPs for this email
    Otp.query.filter_by(email=email).delete()

    # Save new OTP
    new_otp = Otp(email=email, otp=otp, expiry_time=expiry_time)
    db.session.add(new_otp)
    db.session.commit()

    # "Send" OTP
    send_mail(email, "Your OTP Code", f"Your OTP code is: {otp}")

    flash(f"OTP sent to {email}. Please check your console/logs.", "success")
    return redirect(url_for('otp_verification', email=email))


@app.route('/otp_verification', methods=['GET', 'POST'])
def otp_verification():
    email = request.args.get('email')

    if request.method == 'POST':
        entered_otp = request.form['otp']
        stored_otp = Otp.query.filter_by(email=email).first()

        if not stored_otp:
            flash("No OTP found. Please request a new one.", "danger")
            return redirect(url_for('home'))

        if time.time() > stored_otp.expiry_time:
            flash("OTP has expired. Please request a new one.", "danger")
            db.session.delete(stored_otp)
            db.session.commit()
            return redirect(url_for('home'))

        if entered_otp == stored_otp.otp:
            db.session.delete(stored_otp)
            db.session.commit()
            user = User.query.filter_by(email=email).first()
            if user:
                session['role'] = user.role
                session['user'] = email
                session.permanent = True
                login_user(user)
                return redirect(url_for(f'{user.role}_dashboard'))
            else:
                flash("User not found. Please try again.", "danger")
                return redirect(url_for('home'))
        else:
            flash("Invalid OTP. Please try again.", "danger")
            return redirect(url_for('otp_verification', email=email))

    return render_template('otp_verification.html', email=email)


# -------------------- Dashboards --------------------
@app.route('/judge_dashboard', methods=['GET', 'POST'])
@login_required
def judge_dashboard():
    if current_user.role != 'judge':
        return redirect(url_for('home'))
    if request.method == 'POST':
        for idea in Idea.query.all():
            score = request.form.get(f"score_{idea.id}")
            if score:
                idea.score_judge += int(score)
                idea.total_score += int(score)
        db.session.commit()
        update_scores()
        return redirect(url_for('thank_you'))
    return render_template('judge_dashboard.html', ideas=Idea.query.all())


@app.route('/audience_dashboard', methods=['GET', 'POST'])
@login_required
def audience_dashboard():
    if current_user.role != 'audience':
        return redirect(url_for('home'))
    if request.method == 'POST':
        for idea in Idea.query.all():
            score = request.form.get(f"score_{idea.id}")
            if score:
                idea.score_audience += int(score)
                idea.total_score += int(score)
        db.session.commit()
        update_scores()
        return redirect(url_for('thank_you'))
    return render_template('audience_dashboard.html', ideas=Idea.query.all())


@app.route('/admin_dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('home'))
    ideas = Idea.query.all()
    winner = max(ideas, key=lambda idea: idea.total_score, default=None)
    return render_template('admin_dashboard.html', ideas=ideas, winner=winner)


@app.route('/result')
def result():
    calculate_total_scores()
    return render_template('result.html', total_scores=Idea.query.all())


@app.route('/thank_you')
def thank_you():
    return render_template('thank_you.html')


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('home'))


# -------------------- Helpers --------------------
def calculate_total_scores():
    ideas = Idea.query.all()
    for idea in ideas:
        idea.total_score = idea.score_judge + idea.score_audience
    db.session.commit()


def update_scores():
    ideas = Idea.query.all()
    scores = {
        idea.id: {
            'judge': idea.score_judge,
            'audience': idea.score_audience,
            'total': idea.total_score,
            'name': idea.name
        }
        for idea in ideas
    }
    winner = max(ideas, key=lambda idea: idea.total_score, default=None)
    winner_data = {'name': winner.name, 'score': winner.total_score} if winner else None
    socketio.emit('update_scores', {'scores': scores, 'winner': winner_data})


# -------------------- Socket.IO Handlers --------------------
@socketio.on('submit_scores')
def handle_score_submission(data):
    print("[DEBUG] Received scores from client:", data)
    for idea_id, score in data.items():
        print(f"[DEBUG] Processing idea_id={idea_id}, score={score}")
        try:
            idea = Idea.query.get(int(idea_id))
        except ValueError:
            print(f"[ERROR] Invalid idea_id: {idea_id}")
            continue

        if idea:
            if current_user.role == 'judge':
                idea.score_judge += int(score)
                print(f"[DEBUG] Judge added {score} to {idea.name} (new judge_score={idea.score_judge})")
            elif current_user.role == 'audience':
                idea.score_audience += int(score)
                print(f"[DEBUG] Audience added {score} to {idea.name} (new audience_score={idea.score_audience})")

            idea.total_score = idea.score_judge + idea.score_audience
            print(f"[DEBUG] Updated total_score for {idea.name}: {idea.total_score}")
        else:
            print(f"[ERROR] No idea found with id {idea_id}")

    db.session.commit()
    print("[DEBUG] Database commit complete")
    update_scores()


# -------------------- Main --------------------
# -------------------- Main --------------------
if __name__ == '__main__':
    # Start background cleanup thread (works in local dev)
    Thread(target=cleanup_otps, daemon=True).start()

    socketio.run(app, debug=True, port=5000)


