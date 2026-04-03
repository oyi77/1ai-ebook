from pathlib import Path


class DatabaseManager:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self._init_database()

    def get_connection(self):
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_database(self):
        from src.db.schema import create_tables

        with self.get_connection() as conn:
            create_tables(conn)
