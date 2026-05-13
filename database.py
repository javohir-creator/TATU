"""
Database moduli — aiosqlite orqali asinxron SQLite.
"""

import aiosqlite
import json
import hashlib
import os

DB_PATH = os.getenv("DB_PATH", "voting.db")
ANON_SALT = os.getenv("ANON_SALT", "xY9#mK!p2qR@survey")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id      INTEGER PRIMARY KEY,
            username     TEXT,
            full_name    TEXT,
            faculty      TEXT,
            course       TEXT,
            gender       TEXT,
            registered_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS admins (
            admin_id     INTEGER PRIMARY KEY,
            added_by     INTEGER,
            added_at     TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS surveys (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            title        TEXT NOT NULL,
            description  TEXT DEFAULT '',
            created_by   INTEGER NOT NULL,
            is_active    INTEGER DEFAULT 1,
            created_at   TEXT DEFAULT (datetime('now')),
            closed_at    TEXT,
            ai_analysis  TEXT
        );

        CREATE TABLE IF NOT EXISTS survey_questions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            survey_id    INTEGER NOT NULL,
            order_num    INTEGER NOT NULL,
            question     TEXT NOT NULL,
            options      TEXT NOT NULL,
            allow_multi  INTEGER DEFAULT 0,
            q_type       TEXT DEFAULT 'single',
            FOREIGN KEY (survey_id) REFERENCES surveys(id)
        );

        CREATE TABLE IF NOT EXISTS survey_responses (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            survey_id    INTEGER NOT NULL,
            question_id  INTEGER NOT NULL,
            anon_token   TEXT NOT NULL,
            choices      TEXT NOT NULL,
            answered_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(question_id, anon_token),
            FOREIGN KEY (survey_id)   REFERENCES surveys(id),
            FOREIGN KEY (question_id) REFERENCES survey_questions(id)
        );

        CREATE TABLE IF NOT EXISTS text_responses (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            survey_id    INTEGER NOT NULL,
            question_id  INTEGER NOT NULL,
            anon_token   TEXT NOT NULL,
            answer_text  TEXT NOT NULL,
            answered_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(question_id, anon_token),
            FOREIGN KEY (survey_id)   REFERENCES surveys(id),
            FOREIGN KEY (question_id) REFERENCES survey_questions(id)
        );

        CREATE TABLE IF NOT EXISTS active_polls (
            tg_poll_id   TEXT PRIMARY KEY,
            survey_id    INTEGER NOT NULL,
            question_id  INTEGER NOT NULL,
            user_id      INTEGER NOT NULL,
            sent_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS analysis_log (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            survey_id         INTEGER NOT NULL,
            model             TEXT,
            prompt_tokens     INTEGER,
            completion_tokens INTEGER,
            analysis          TEXT,
            created_at        TEXT DEFAULT (datetime('now'))
        );
        """)
        await db.commit()


async def register_user(user_id: int, username: str, full_name: str,
                         faculty: str, course: str, gender: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO users (user_id, username, full_name, faculty, course, gender)
               VALUES (?,?,?,?,?,?)""",
            (user_id, username, full_name, faculty, course, gender)
        )
        await db.commit()


async def get_user(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None


async def is_registered(user_id: int) -> bool:
    return (await get_user(user_id)) is not None


async def get_users_by_filter(faculties: list = None, courses: list = None, genders: list = None) -> list:
    q = "SELECT user_id FROM users WHERE 1=1"
    params = []
    if faculties:
        placeholders = ",".join("?" * len(faculties))
        q += f" AND faculty IN ({placeholders})"
        params.extend(faculties)
    if courses:
        placeholders = ",".join("?" * len(courses))
        q += f" AND course IN ({placeholders})"
        params.extend(courses)
    if genders:
        placeholders = ",".join("?" * len(genders))
        q += f" AND gender IN ({placeholders})"
        params.extend(genders)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(q, params) as cur:
            rows = await cur.fetchall()
    return [r[0] for r in rows]


async def get_all_user_ids() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            rows = await cur.fetchall()
    return [r[0] for r in rows]


async def add_admin(admin_id: int, added_by: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO admins (admin_id, added_by) VALUES (?,?)",
            (admin_id, added_by)
        )
        await db.commit()


async def get_db_admins() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT admin_id FROM admins") as cur:
            rows = await cur.fetchall()
    return [r[0] for r in rows]


async def create_survey(title: str, description: str,
                        questions: list, admin_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO surveys (title, description, created_by) VALUES (?,?,?)",
            (title, description, admin_id)
        )
        survey_id = cur.lastrowid
        for idx, q in enumerate(questions):
            q_type = q.get("q_type", "single")
            allow_multi = 1 if q_type == "multi" else 0
            await db.execute(
                "INSERT INTO survey_questions (survey_id, order_num, question, options, allow_multi, q_type)"
                " VALUES (?,?,?,?,?,?)",
                (
                    survey_id, idx,
                    q["question"],
                    json.dumps(q.get("options", []), ensure_ascii=False),
                    allow_multi,
                    q_type,
                )
            )
        await db.commit()
    return survey_id


async def get_survey(survey_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM surveys WHERE id=?", (survey_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["ai_analysis"] = json.loads(d["ai_analysis"]) if d["ai_analysis"] else None
        async with db.execute(
            "SELECT * FROM survey_questions WHERE survey_id=? ORDER BY order_num",
            (survey_id,)
        ) as cur:
            qs = await cur.fetchall()
        d["questions"] = []
        for q in qs:
            qd = dict(q)
            qd["options"] = json.loads(qd["options"])
            d["questions"].append(qd)
        return d


async def list_surveys(active_only: bool = False) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        q = "SELECT * FROM surveys"
        if active_only:
            q += " WHERE is_active=1"
        q += " ORDER BY id DESC"
        async with db.execute(q) as cur:
            rows = await cur.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["ai_analysis"] = json.loads(d["ai_analysis"]) if d["ai_analysis"] else None
            async with db.execute(
                "SELECT COUNT(*) as cnt FROM survey_questions WHERE survey_id=?", (d["id"],)
            ) as cur2:
                cnt_row = await cur2.fetchone()
            d["question_count"] = cnt_row["cnt"]
            result.append(d)
        return result


async def close_survey(survey_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE surveys SET is_active=0, closed_at=datetime('now') WHERE id=?",
            (survey_id,)
        )
        await db.commit()


async def delete_survey(survey_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM survey_responses WHERE survey_id=?", (survey_id,))
        await db.execute("DELETE FROM text_responses WHERE survey_id=?", (survey_id,))
        await db.execute("DELETE FROM active_polls WHERE survey_id=?", (survey_id,))
        await db.execute("DELETE FROM survey_questions WHERE survey_id=?", (survey_id,))
        await db.execute("DELETE FROM surveys WHERE id=?", (survey_id,))
        await db.commit()


async def delete_question(question_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM survey_questions WHERE id=?", (question_id,))
        await db.commit()


async def update_question(question_id: int, question_text: str, options: list, q_type: str):
    allow_multi = 1 if q_type == "multi" else 0
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE survey_questions SET question=?, options=?, allow_multi=?, q_type=? WHERE id=?",
            (question_text, json.dumps(options, ensure_ascii=False), allow_multi, q_type, question_id)
        )
        await db.commit()


async def save_ai_analysis(survey_id: int, analysis: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE surveys SET ai_analysis=? WHERE id=?",
            (json.dumps(analysis, ensure_ascii=False), survey_id)
        )
        await db.commit()


async def get_questions(survey_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM survey_questions WHERE survey_id=? ORDER BY order_num",
            (survey_id,)
        ) as cur:
            rows = await cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["options"] = json.loads(d["options"])
            result.append(d)
        return result


async def register_active_poll(tg_poll_id: str, survey_id: int,
                                question_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO active_polls (tg_poll_id, survey_id, question_id, user_id)"
            " VALUES (?,?,?,?)",
            (tg_poll_id, survey_id, question_id, user_id)
        )
        await db.commit()


async def get_active_poll(tg_poll_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM active_polls WHERE tg_poll_id=?", (tg_poll_id,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None


async def remove_active_poll(tg_poll_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM active_polls WHERE tg_poll_id=?", (tg_poll_id,))
        await db.commit()


def make_anon_token(user_id: int, question_id: int) -> str:
    raw = f"{user_id}:{question_id}:{ANON_SALT}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def save_response(survey_id: int, question_id: int,
                        user_id: int, choices: list) -> bool:
    token = make_anon_token(user_id, question_id)
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO survey_responses (survey_id, question_id, anon_token, choices)"
                " VALUES (?,?,?,?)",
                (survey_id, question_id, token, json.dumps(choices))
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def save_text_response(survey_id: int, question_id: int,
                              user_id: int, answer_text: str) -> bool:
    token = make_anon_token(user_id, question_id)
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO text_responses (survey_id, question_id, anon_token, answer_text)"
                " VALUES (?,?,?,?)",
                (survey_id, question_id, token, answer_text)
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def has_answered(user_id: int, question_id: int, q_type: str = "single") -> bool:
    token = make_anon_token(user_id, question_id)
    async with aiosqlite.connect(DB_PATH) as db:
        if q_type == "text":
            async with db.execute(
                "SELECT 1 FROM text_responses WHERE question_id=? AND anon_token=?",
                (question_id, token)
            ) as cur:
                return await cur.fetchone() is not None
        else:
            async with db.execute(
                "SELECT 1 FROM survey_responses WHERE question_id=? AND anon_token=?",
                (question_id, token)
            ) as cur:
                return await cur.fetchone() is not None


async def has_completed_survey(user_id: int, survey_id: int) -> bool:
    qs = await get_questions(survey_id)
    if not qs:
        return False
    for q in qs:
        if not await has_answered(user_id, q["id"], q.get("q_type", "single")):
            return False
    return True


async def get_survey_results(survey_id: int) -> dict:
    qs = await get_questions(survey_id)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT question_id, choices FROM survey_responses WHERE survey_id=?",
            (survey_id,)
        ) as cur:
            responses = await cur.fetchall()
        async with db.execute(
            "SELECT question_id, answer_text FROM text_responses WHERE survey_id=?",
            (survey_id,)
        ) as cur:
            text_responses = await cur.fetchall()

    raw = {}
    for r in responses:
        qid = r["question_id"]
        raw.setdefault(qid, []).append(json.loads(r["choices"]))

    text_raw = {}
    for r in text_responses:
        qid = r["question_id"]
        text_raw.setdefault(qid, []).append(r["answer_text"])

    result = {}
    for q in qs:
        qid = q["id"]
        q_type = q.get("q_type", "single")
        if q_type == "text":
            answers = text_raw.get(qid, [])
            result[qid] = {
                "question": q["question"],
                "options": [],
                "total": len(answers),
                "counts": {},
                "text_answers": answers,
                "q_type": "text",
            }
        else:
            votes = raw.get(qid, [])
            counts = {}
            for vote in votes:
                for idx in vote:
                    counts[idx] = counts.get(idx, 0) + 1
            result[qid] = {
                "question": q["question"],
                "options": q["options"],
                "total": len(votes),
                "counts": counts,
                "q_type": q_type,
            }
    return result


async def log_analysis(survey_id: int, model: str,
                       prompt_tokens: int, completion_tokens: int, text: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO analysis_log (survey_id, model, prompt_tokens, completion_tokens, analysis)"
            " VALUES (?,?,?,?,?)",
            (survey_id, model, prompt_tokens, completion_tokens, text)
        )
        await db.commit()
