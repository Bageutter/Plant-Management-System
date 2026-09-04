"""Demo seed data for Auth.

Runs on startup only when the `users` table is empty (a fresh database). It
creates one demo account and 12 garden-ownership rows so the showcase can log in
immediately and every garden already has content.

    email:    demo@plant.test
    password: demogarden

The ownership rows point at Virtual Garden ids 1..12 — which is exactly what
vgarden/seed_data.py assigns from a fresh database, so `docker compose down -v`
followed by `docker compose up` gives a matching demo dataset across both
services.
"""

from extensions import db
from models import Garden, User

DEMO_EMAIL = "demo@plant.test"
DEMO_PASSWORD = "demogarden"
DEMO_GARDEN_COUNT = 12

# A few extra accounts so the `users` table is populated too. They share the demo
# password and own no gardens; only demo@plant.test is used in the showcase.
EXTRA_MEMBERS = [
    "amy@plant.test", "guhan@plant.test", "yunz@plant.test", "tutor@plant.test",
    "sam@plant.test", "ravi@plant.test", "mia@plant.test", "leo@plant.test",
    "nina@plant.test", "omar@plant.test", "zoe@plant.test",
]


def seed_demo_data() -> None:
    if User.query.first() is not None:
        return

    demo = User(email=DEMO_EMAIL)
    demo.set_password(DEMO_PASSWORD)
    db.session.add(demo)
    db.session.flush()

    for garden_id in range(1, DEMO_GARDEN_COUNT + 1):
        db.session.add(Garden(garden_id=garden_id, user_id=demo.id))

    for email in EXTRA_MEMBERS:
        member = User(email=email)
        member.set_password(DEMO_PASSWORD)
        db.session.add(member)

    db.session.commit()
