from starlette.requests import HTTPConnection

from config import Settings


def get_settings(conn: HTTPConnection) -> Settings:
    return conn.app.state.settings
