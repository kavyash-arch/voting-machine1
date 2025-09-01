from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import random
import string
import time
import os
from os import getenv

app = Flask(__name__)
app.secret_key = getenv("SECRET_KEY", "hello123")  # Use strong secret key in production

# Enable Flask-SocketIO with CORS
socketio = SocketIO(app, cors_allowed_origins="*")


db_url = os.environ.get("DATABASE_URL")

# If no DATABASE_URL (like in local dev), use local PostgreSQL
if not db_url:
    db_url = "postgresql+psycopg2://root:11111@127.0.0.1/voting_db"

# Fix Render’s "postgres://" prefix if needed
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize DB
db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "home"

# ---------------- MODELS ---------------- #
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.String(50), nullable=False)

class Idea(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    score_judge = db.Column(db.Integer, default=0)
    score_audience = db.Column(db.Integer, default=0)
    total_score = db.Column(db.Integer, default=0)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------------- OTP SYSTEM ---------------- #
otp_storage = {}

def generate_otp():
    return ''.join(random.choices(string.digits, k=6))

def is_otp_expired(stored_otp):
    return not stored_otp or time.time() > stored_otp["expiry_time"]

def send_otp_console(email, otp):
    print(f"📩 OTP for {email}: {otp}", flush=True)

# ---------------- HELPERS ---------------- #
def calculate_total_scores():
    ideas = Idea.query.all()
    for idea in ideas:
        idea.total_score = idea.score_judge + idea.score_audience
    db.session.commit()

# ---------------- ROUTES ---------------- #
@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        email = request.form["email"]
        role = request.form["role"]
        user = User.query.filter_by(email=email, role=role).first()
        if user:
            login_user(user)
            session.permanent = True
            return redirect(url_for(f"{role}_dashboard"))
        flash("Invalid email or role.", "danger")
    return render_template("login.html")

@app.route("/send_otp", methods=["POST"])
def send_otp():
    email = request.form["email"]
    role = request.form["role"]

    if not email.endswith("@amdocs.com"):
        flash("Only @amdocs.com email addresses are allowed!", "danger")
        return redirect(url_for("home"))

    user = User.query.filter_by(email=email).first()

    if role in ["judge", "admin"]:
        if not user:
            flash("Email not registered!", "danger")
            return redirect(url_for("home"))
        if user.role != role:
            flash("Role mismatch. Please choose the correct role.", "danger")
            return redirect(url_for("home"))

    if role == "audience" and not user:
        user = User(email=email, role=role)
        db.session.add(user)
        db.session.commit()

    otp = generate_otp()
    expiry_time = time.time() + 900
    otp_storage[email] = {"otp": otp, "expiry_time": expiry_time}

    send_otp_console(email, otp)  # Console print instead of email

    flash(f"OTP generated for {email}. Please check your console.", "success")
    return redirect(url_for("otp_verification", email=email))

@app.route("/otp_verification", methods=["GET", "POST"])
def otp_verification():
    email = request.args.get("email")
    if request.method == "POST":
        entered_otp = request.form["otp"]
        stored_otp = otp_storage.get(email, None)

        if not stored_otp:
            flash("No OTP found for this email. Please request a new one.", "danger")
            return redirect(url_for("home"))

        if is_otp_expired(stored_otp):
            flash("OTP has expired. Please request a new one.", "danger")
            del otp_storage[email]
            return redirect(url_for("home"))

        if entered_otp == stored_otp["otp"]:
            del otp_storage[email]
            user = User.query.filter_by(email=email).first()
            if user:
                session["role"] = user.role
                session["user"] = email
                session.permanent = True
                login_user(user)
                return redirect(url_for(f"{user.role}_dashboard"))
            else:
                flash("User not found. Please try again.", "danger")
                return redirect(url_for("home"))
        else:
            flash("Invalid OTP. Please try again.", "danger")
            return redirect(url_for("otp_verification", email=email))

    return render_template("otp_verification.html", email=email)

# ---------------- OTHER ROUTES (unchanged) ---------------- #
@app.route("/login", methods=["POST"])
def login():
    email = request.form["email"]
    role = request.form["role"]
    if not email.endswith("@amdocs.com"):
        flash("Only @amdocs.com email addresses are allowed!", "danger")
        return redirect(url_for("home"))

    user = User.query.filter_by(email=email, role=role).first()
    if not user:
        user = User(email=email, role=role)
        db.session.add(user)
        db.session.commit()

    login_user(user)
    session.permanent = True
    session["role"] = user.role
    session["user"] = email
    return redirect(url_for(f"{role}_dashboard"))

@app.route("/judge_dashboard", methods=["GET", "POST"])
@login_required
def judge_dashboard():
    if current_user.role != "judge":
        return redirect(url_for("home"))
    if request.method == "POST":
        for idea in Idea.query.all():
            score = request.form.get(f"score_{idea.id}")
            if score:
                idea.score_judge += int(score)
                idea.total_score += int(score)
        db.session.commit()
        update_scores()
        return redirect(url_for("thank_you"))
    return render_template("judge_dashboard.html", ideas=Idea.query.all())

@app.route("/audience_dashboard", methods=["GET", "POST"])
@login_required
def audience_dashboard():
    if current_user.role != "audience":
        return redirect(url_for("home"))
    if request.method == "POST":
        for idea in Idea.query.all():
            score = request.form.get(f"score_{idea.id}")
            if score:
                idea.score_audience += int(score)
                idea.total_score += int(score)
        db.session.commit()
        update_scores()
        return redirect(url_for("thank_you"))
    return render_template("audience_dashboard.html", ideas=Idea.query.all())

def update_scores():
    ideas = Idea.query.all()
    scores = {idea.id: {"judge": idea.score_judge, "audience": idea.score_audience,
                        "total": idea.total_score, "name": idea.name} for idea in ideas}
    winner = max(ideas, key=lambda idea: idea.total_score, default=None)
    winner_data = {"name": winner.name, "score": winner.total_score} if winner else None
    socketio.emit("update_scores", {"scores": scores, "winner": winner_data})

@app.route("/admin_dashboard")
@login_required
def admin_dashboard():
    if current_user.role != "admin":
        return redirect(url_for("home"))
    ideas = Idea.query.all()
    winner = max(ideas, key=lambda idea: idea.total_score, default=None)
    return render_template("admin_dashboard.html", ideas=ideas, winner=winner)

@app.route("/result")
def result():
    calculate_total_scores()
    return render_template("result.html", total_scores=Idea.query.all())

@app.route("/thank_you")
def thank_you():
    return render_template("thank_you.html")

@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("home"))

@socketio.on("submit_scores")
def handle_score_submission(data):
    for idea_id, score in data.items():
        idea = Idea.query.get(int(idea_id))
        if idea:
            if current_user.role == "judge":
                idea.score_judge += int(score)
            elif current_user.role == "audience":
                idea.score_audience += int(score)
            idea.total_score = idea.score_judge + idea.score_audience
        db.session.commit()
    update_scores()

# ---------------- ENTRY POINT ---------------- #
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    socketio.run(app, host="0.0.0.0", port=int(getenv("PORT", 5000)), debug=True)
