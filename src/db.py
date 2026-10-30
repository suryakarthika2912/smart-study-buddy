import os
import re
import sqlite3

try:
    import psycopg2
    from psycopg2.extras import DictCursor
    from psycopg2.pool import SimpleConnectionPool
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

_pg_pool = None

def get_database_uri():
    raw_uri = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("POSTGRES_URL")
        or os.environ.get("POSTGRES_URL_NON_POOLING")
        or os.environ.get("POSTGRES_PRISMA_URL")
        or os.environ.get("DATABASE_PATH")
        or "study_buddy.db"
    )
    if isinstance(raw_uri, str):
        raw_uri = raw_uri.strip().strip("'\"")
    return raw_uri

def is_postgres_uri(uri):
    if not uri or not isinstance(uri, str):
        return False
    cleaned = uri.strip().strip("'\"")
    return cleaned.startswith("postgres://") or cleaned.startswith("postgresql://")

def get_pg_pool(dsn):
    global _pg_pool
    if _pg_pool is None:
        # Standard serverless pool sizing (min 1, max 5)
        _pg_pool = SimpleConnectionPool(minconn=1, maxconn=5, dsn=dsn)
    return _pg_pool


def translate_sql_placeholders(query):
    """
    Translates parameter placeholder ? to %s in SQL queries,
    ignoring ? inside string literals ('...'), identifiers ("..."),
    and comments (-- ... or /* ... */).
    """
    out = []
    i = 0
    n = len(query)

    while i < n:
        ch = query[i]

        # Single-line comment: -- ...
        if ch == '-' and i + 1 < n and query[i + 1] == '-':
            end = query.find('\n', i + 2)
            if end == -1:
                out.append(query[i:])
                break
            else:
                out.append(query[i:end + 1])
                i = end + 1
                continue

        # Block comment: /* ... */
        if ch == '/' and i + 1 < n and query[i + 1] == '*':
            end = query.find('*/', i + 2)
            if end == -1:
                out.append(query[i:])
                break
            else:
                out.append(query[i:end + 2])
                i = end + 2
                continue

        # String literal: '...'
        if ch == "'":
            out.append(ch)
            i += 1
            while i < n:
                cur = query[i]
                out.append(cur)
                if cur == "'":
                    # Escaped quote: ''
                    if i + 1 < n and query[i + 1] == "'":
                        out.append(query[i + 1])
                        i += 2
                        continue
                    else:
                        i += 1
                        break
                i += 1
            continue

        # Quoted identifier: "..."
        if ch == '"':
            out.append(ch)
            i += 1
            while i < n:
                cur = query[i]
                out.append(cur)
                if cur == '"':
                    if i + 1 < n and query[i + 1] == '"':
                        out.append(query[i + 1])
                        i += 2
                        continue
                    else:
                        i += 1
                        break
                i += 1
            continue

        # Placeholder ?
        if ch == '?':
            out.append('%s')
            i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def is_begin_statement(query):
    """Checks if a SQL statement is a transaction-start command."""
    cleaned = query.strip().rstrip(";").strip().upper()
    return cleaned in ("BEGIN", "BEGIN IMMEDIATE", "BEGIN TRANSACTION", "BEGIN DEFERRED", "BEGIN EXCLUSIVE")


class DBCursorWrapper:
    """Cursor wrapper providing unified interface for SQLite and PostgreSQL."""
    def __init__(self, raw_cursor, is_postgres=False):
        self.raw_cursor = raw_cursor
        self.is_postgres = is_postgres

    def _translate_query(self, query):
        if not self.is_postgres:
            return query
        # 1. Translate parameter placeholder ? to %s (excluding strings, comments, identifiers)
        translated = translate_sql_placeholders(query)
        # 2. Translate SQLite COLLATE NOCASE to standard SQL
        translated = re.sub(r"\bCOLLATE\s+NOCASE\b", "", translated, flags=re.IGNORECASE)
        return translated

    def execute(self, query, params=None):
        if self.is_postgres and is_begin_statement(query):
            # In psycopg2, transactions are managed automatically when autocommit=False.
            # Issuing an explicit BEGIN triggers 'WARNING: there is already a transaction in progress'.
            conn = getattr(self.raw_cursor, "connection", None)
            if conn is None or not getattr(conn, "autocommit", False):
                return self

        sql = self._translate_query(query)
        if params is not None:
            # Handle tuple/list params
            return self.raw_cursor.execute(sql, tuple(params) if isinstance(params, (list, tuple)) else params)
        return self.raw_cursor.execute(sql)

    def executemany(self, query, seq_of_params):
        if self.is_postgres and is_begin_statement(query):
            conn = getattr(self.raw_cursor, "connection", None)
            if conn is None or not getattr(conn, "autocommit", False):
                return self
        sql = self._translate_query(query)
        return self.raw_cursor.executemany(sql, seq_of_params)

    def fetchone(self):
        return self.raw_cursor.fetchone()

    def fetchall(self):
        return self.raw_cursor.fetchall()

    def fetchmany(self, size=None):
        return self.raw_cursor.fetchmany(size) if size else self.raw_cursor.fetchmany()

    @property
    def rowcount(self):
        return self.raw_cursor.rowcount

    @property
    def description(self):
        return self.raw_cursor.description

    def close(self):
        try:
            self.raw_cursor.close()
        except Exception:
            pass

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class DBConnectionWrapper:
    """Connection wrapper ensuring uniform commit, rollback, and dict-like row access."""
    def __init__(self, raw_conn, is_postgres=False, from_pool=False):
        self.raw_conn = raw_conn
        self.is_postgres = is_postgres
        self.from_pool = from_pool

    def cursor(self):
        if self.is_postgres:
            raw_cur = self.raw_conn.cursor(cursor_factory=DictCursor)
        else:
            raw_cur = self.raw_conn.cursor()
        return DBCursorWrapper(raw_cur, self.is_postgres)

    def execute(self, query, params=None):
        cur = self.cursor()
        cur.execute(query, params)
        return cur

    def commit(self):
        self.raw_conn.commit()

    def rollback(self):
        try:
            self.raw_conn.rollback()
        except Exception:
            pass

    def close(self):
        global _pg_pool
        if self.raw_conn is None:
            return

        if self.is_postgres and self.from_pool and _pg_pool is not None:
            raw_conn = self.raw_conn
            self.raw_conn = None
            rollback_ok = True
            try:
                # If connection is still open, safely roll back any uncommitted/aborted transaction
                if not getattr(raw_conn, "closed", False):
                    raw_conn.rollback()
            except Exception:
                rollback_ok = False

            try:
                # If rollback failed or connection is closed/broken, discard it with close=True
                is_closed = getattr(raw_conn, "closed", False)
                if not rollback_ok or is_closed:
                    _pg_pool.putconn(raw_conn, close=True)
                else:
                    _pg_pool.putconn(raw_conn, close=False)
            except Exception:
                try:
                    raw_conn.close()
                except Exception:
                    pass
        else:
            raw_conn = self.raw_conn
            self.raw_conn = None
            try:
                raw_conn.close()
            except Exception:
                pass

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        self.close()


def get_db_connection(database_uri=None):
    """Factory returning unified DBConnectionWrapper for SQLite or PostgreSQL."""
    uri = database_uri or get_database_uri()

    if is_postgres_uri(uri):
        if not HAS_PSYCOPG2:
            raise RuntimeError("PostgreSQL driver (psycopg2) is not installed. Please install psycopg2-binary.")
        # Fix postgres:// URL format for psycopg2 if needed
        if uri.startswith("postgres://"):
            uri = "postgresql://" + uri[len("postgres://"):]

        try:
            pool = get_pg_pool(uri)
            raw_conn = pool.getconn()
            if getattr(raw_conn, "closed", 0) != 0:
                try:
                    pool.putconn(raw_conn, close=True)
                except Exception:
                    pass
                raw_conn = psycopg2.connect(uri)
                return DBConnectionWrapper(raw_conn, is_postgres=True, from_pool=False)
            return DBConnectionWrapper(raw_conn, is_postgres=True, from_pool=True)
        except Exception:
            # Fall back to direct connection if pooling fails or pool is exhausted
            raw_conn = psycopg2.connect(uri)
            return DBConnectionWrapper(raw_conn, is_postgres=True, from_pool=False)
    else:
        # SQLite
        db_path = uri
        if db_path.startswith("sqlite:///"):
            db_path = db_path[10:]
        elif db_path.startswith("sqlite://"):
            db_path = db_path[9:]

        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        conn = sqlite3.connect(db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return DBConnectionWrapper(conn, is_postgres=False)


def setup_database_schema(conn=None):
    """Initializes schema on the configured database without dropping existing data."""
    close_when_done = False
    if conn is None:
        conn = get_db_connection()
        close_when_done = True

    try:
        cur = conn.cursor()
        if conn.is_postgres:
            # PostgreSQL Schema
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_lower_username_idx ON users (LOWER(username))")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS study_plans (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    name VARCHAR(150),
                    subject VARCHAR(100),
                    priority INTEGER,
                    days INTEGER,
                    daily_hours REAL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS study_progress (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    subject VARCHAR(100),
                    planned_hours REAL,
                    completed_hours REAL,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS study_goals (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    goal VARCHAR(150),
                    target_hours REAL,
                    completed_hours REAL DEFAULT 0,
                    deadline DATE,
                    status VARCHAR(50) DEFAULT 'Pending'
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS study_dates (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    study_date DATE NOT NULL,
                    UNIQUE(user_id, study_date)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS study_tasks (
                    id SERIAL PRIMARY KEY,
                    plan_id INTEGER NOT NULL REFERENCES study_plans(id) ON DELETE CASCADE,
                    user_id INTEGER REFERENCES users(id),
                    title VARCHAR(150) NOT NULL,
                    due_date DATE,
                    status VARCHAR(50) NOT NULL DEFAULT 'Pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            # SQLite Schema
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS study_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES users(id),
                    name TEXT,
                    subject TEXT,
                    priority INTEGER,
                    days INTEGER,
                    daily_hours REAL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS study_progress (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES users(id),
                    subject TEXT,
                    planned_hours REAL,
                    completed_hours REAL,
                    added_at TEXT
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS study_goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES users(id),
                    goal TEXT,
                    target_hours REAL,
                    completed_hours REAL DEFAULT 0,
                    deadline TEXT,
                    status TEXT DEFAULT 'Pending'
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS study_dates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES users(id),
                    study_date TEXT NOT NULL,
                    UNIQUE(user_id, study_date)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS study_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id INTEGER NOT NULL,
                    user_id INTEGER REFERENCES users(id),
                    title TEXT NOT NULL,
                    due_date TEXT,
                    status TEXT NOT NULL DEFAULT 'Pending',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (plan_id) REFERENCES study_plans(id)
                )
            """)

            # Non-destructive column checks for existing SQLite tables
            for table in ("study_plans", "study_tasks", "study_goals", "study_progress"):
                cur.execute(f"PRAGMA table_info({table})")
                cols = [r[1] for r in cur.fetchall()]
                if "user_id" not in cols:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER REFERENCES users(id)")

            cur.execute("PRAGMA table_info(study_progress)")
            prog_cols = [r[1] for r in cur.fetchall()]
            if "added_at" not in prog_cols:
                cur.execute("ALTER TABLE study_progress ADD COLUMN added_at TEXT")

            cur.execute("PRAGMA table_info(study_dates)")
            date_cols = [r[1] for r in cur.fetchall()]
            if "user_id" not in date_cols:
                cur.execute("""
                    CREATE TABLE study_dates_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER REFERENCES users(id),
                        study_date TEXT NOT NULL,
                        UNIQUE(user_id, study_date)
                    )
                """)
                cur.execute("INSERT OR IGNORE INTO study_dates_new (id, study_date) SELECT id, study_date FROM study_dates")
                cur.execute("DROP TABLE study_dates")
                cur.execute("ALTER TABLE study_dates_new RENAME TO study_dates")

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if close_when_done:
            conn.close()

