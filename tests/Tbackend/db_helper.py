from shutil import rmtree
from tempfile import mkdtemp

from flask import Flask

from backend.internals.db import DBConnectionManager, set_db_location, setup_db


class TempDatabase:
    """
    Context manager that gives a test a real, throwaway Kapowarr database
    (fully set up and migrated), inside a Flask app context.
    """

    def __enter__(self) -> 'TempDatabase':
        DBConnectionManager.close_connection_of_thread()
        self.folder = mkdtemp()
        set_db_location(self.folder)
        self.app_context = Flask(__name__).app_context()
        self.app_context.push()
        setup_db()
        return self

    def __exit__(self, *args) -> bool:
        DBConnectionManager.close_connection_of_thread()
        self.app_context.pop()
        rmtree(self.folder, ignore_errors=True)
        return False
