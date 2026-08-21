import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "instance", "vgarden.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Browser-facing base URL of the auth service, used in links rendered to the user.
    AUTH_PUBLIC_URL = os.environ.get("AUTH_PUBLIC_URL", "http://localhost:5001")
