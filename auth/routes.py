import requests
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from extensions import db
from forms import LoginForm, RegisterForm
from models import Garden, User

bp = Blueprint("auth", __name__)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("auth.account"))

    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if User.query.filter_by(email=email).first():
            form.email.errors.append("An account with this email already exists.")
        else:
            user = User(email=email)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            return redirect(url_for("auth.account"))

    return render_template("register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.account"))

    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = User.query.filter_by(email=email).first()
        if user is None or not user.check_password(form.password.data):
            form.password.errors.append("Invalid email or password.")
        else:
            login_user(user)
            return redirect(url_for("auth.account"))

    return render_template("login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@bp.route("/account")
@login_required
def account():
    ownerships = current_user.gardens
    gardens = []
    gardens_error = None

    if ownerships:
        try:
            resp = requests.get(
                f"{current_app.config['VGARDEN_URL']}/gardens",
                params={"owner_id": current_user.id},
                timeout=5,
            )
            resp.raise_for_status()
        except requests.RequestException:
            gardens_error = "Couldn't load your gardens right now."
        else:
            by_id = {g["id"]: g for g in resp.json()}
            gardens = [by_id[o.garden_id] for o in ownerships if o.garden_id in by_id]

    return render_template(
        "account.html",
        user=current_user,
        gardens=gardens,
        gardens_error=gardens_error,
        vgarden_public_url=current_app.config["VGARDEN_PUBLIC_URL"],
        health_public_url=current_app.config["HEALTH_PUBLIC_URL"],
    )


@bp.route("/gardens", methods=["POST"])
@login_required
def create_garden():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Garden name is required.", "error")
        return redirect(url_for("auth.account"))

    try:
        resp = requests.post(
            f"{current_app.config['VGARDEN_URL']}/gardens",
            json={"owner_id": current_user.id, "name": name},
            timeout=5,
        )
    except requests.RequestException:
        flash("Couldn't reach the garden service. Please try again.", "error")
        return redirect(url_for("auth.account"))

    if resp.status_code != 201:
        flash("Couldn't create that garden.", "error")
        return redirect(url_for("auth.account"))

    garden_id = resp.json()["id"]
    db.session.add(Garden(garden_id=garden_id, user_id=current_user.id))
    db.session.commit()
    flash(f'Added "{name}".', "success")
    return redirect(url_for("auth.account"))


@bp.route("/gardens/<int:garden_id>/delete", methods=["POST"])
@login_required
def delete_garden(garden_id):
    ownership = Garden.query.filter_by(garden_id=garden_id, user_id=current_user.id).first()
    if ownership is None:
        flash("Garden not found.", "error")
        return redirect(url_for("auth.account"))

    try:
        resp = requests.get(f"{current_app.config['VGARDEN_URL']}/gardens/{garden_id}", timeout=5)
    except requests.RequestException:
        flash("Couldn't reach the garden service. Please try again.", "error")
        return redirect(url_for("auth.account"))

    if resp.status_code != 200:
        flash("Garden not found.", "error")
        return redirect(url_for("auth.account"))

    actual_name = resp.json()["name"]
    confirm_name = (request.form.get("confirm_name") or "").strip()
    if confirm_name != actual_name:
        flash("The name you typed didn't match. Nothing was deleted.", "error")
        return redirect(url_for("auth.account"))

    try:
        del_resp = requests.delete(f"{current_app.config['VGARDEN_URL']}/gardens/{garden_id}", timeout=5)
    except requests.RequestException:
        flash("Couldn't reach the garden service. Please try again.", "error")
        return redirect(url_for("auth.account"))

    if del_resp.status_code not in (204, 404):
        flash("Couldn't delete that garden.", "error")
        return redirect(url_for("auth.account"))

    db.session.delete(ownership)
    db.session.commit()
    flash(f'Deleted "{actual_name}".', "success")
    return redirect(url_for("auth.account"))


@bp.route("/me")
@login_required
def me():
    return jsonify({"id": current_user.id, "email": current_user.email})
