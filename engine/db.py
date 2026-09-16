# 每小说 SQLite 运行时知识库
# Bible JSON = 出厂设定种子；本库 = 随章节生长、可查询的"运行记忆"

import hashlib
import json
import sqlite3
from pathlib import Path

from engine.chapter_files import chapter_files, parse_chapter_number

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS characters(
  name TEXT PRIMARY KEY, role TEXT, voice_print TEXT,
  first_chapter INTEGER, profile_json TEXT, updated_chapter INTEGER);
CREATE TABLE IF NOT EXISTS character_states(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chapter INTEGER NOT NULL, character TEXT NOT NULL, state_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_cs ON character_states(character, chapter);
CREATE TABLE IF NOT EXISTS chapter_summaries(
  chapter INTEGER PRIMARY KEY, summary TEXT NOT NULL, content_hash TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS clues(
  id TEXT PRIMARY KEY, name TEXT, type TEXT, description TEXT,
  introduced_ch INTEGER, intended_reveal_ch INTEGER, resolved INTEGER DEFAULT 0,
  state_json TEXT, updated_ch INTEGER);
CREATE TABLE IF NOT EXISTS foreshadowing(
  id TEXT PRIMARY KEY, name TEXT, status TEXT DEFAULT 'pending',
  planted_ch INTEGER, payoff_ch INTEGER, resolved_ch INTEGER,
  description TEXT, hinted_chs TEXT DEFAULT '[]', scope TEXT,
  importance TEXT, touch_interval INTEGER, payoff_start_ch INTEGER,
  payoff_end_ch INTEGER);
CREATE TABLE IF NOT EXISTS chapter_facts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chapter INTEGER NOT NULL, kind TEXT, subject TEXT, content TEXT, scene_id INTEGER,
  UNIQUE(chapter, kind, subject, content));
CREATE INDEX IF NOT EXISTS idx_facts_ch ON chapter_facts(chapter);
CREATE TABLE IF NOT EXISTS style_hits(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chapter INTEGER NOT NULL, category TEXT, pattern TEXT, count INTEGER,
  UNIQUE(chapter, category, pattern));
CREATE TABLE IF NOT EXISTS lessons(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chapter INTEGER, issue TEXT, fix TEXT, source TEXT DEFAULT 'user',
  UNIQUE(chapter, issue, fix));
CREATE TABLE IF NOT EXISTS motifs(
  id TEXT PRIMARY KEY, name TEXT, description TEXT, used_chs TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS chapter_log(
  chapter INTEGER PRIMARY KEY, title TEXT, status TEXT DEFAULT 'generated',
  words INTEGER, reader_score REAL, would_continue INTEGER,
  violations INTEGER, created_at TEXT DEFAULT (datetime('now','localtime')));
"""


class NovelDB:
    def __init__(self, novel_dir: Path, auto_import: bool = True):
        self.novel_dir = Path(novel_dir)
        db_dir = self.novel_dir / "db"
        db_dir.mkdir(exist_ok=True)
        self.path = db_dir / "novel.db"
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()
        self.conn.execute(
            "INSERT OR IGNORE INTO meta(key,value) VALUES('created_from_bible','v1')")
        self.conn.commit()
        if auto_import:
            self.ensure_imported()

    def close(self):
        self.conn.close()

    def _migrate(self):
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        self.conn.executescript(SCHEMA)
        if version < 1:
            self.conn.execute("PRAGMA user_version=1")
            version = 1
        if version < 2:
            self.conn.execute(
                "DELETE FROM character_states WHERE id NOT IN ("
                "SELECT MAX(id) FROM character_states GROUP BY chapter, character)"
            )
            self.conn.execute("PRAGMA user_version=2")
        self.conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_character_states_chapter_character "
            "ON character_states(chapter, character)"
        )
        if version < 3:
            columns = {
                row[1] for row in self.conn.execute(
                    "PRAGMA table_info(foreshadowing)"
                ).fetchall()
            }
            for name, sql_type in (
                ("scope", "TEXT"), ("importance", "TEXT"),
                ("touch_interval", "INTEGER"),
                ("payoff_start_ch", "INTEGER"), ("payoff_end_ch", "INTEGER"),
            ):
                if name not in columns:
                    self.conn.execute(
                        f"ALTER TABLE foreshadowing ADD COLUMN {name} {sql_type}"
                    )
            self.conn.execute("PRAGMA user_version=3")
        self.conn.commit()

    def _bible_signature(self) -> str:
        files = ("characters.json", "clues.json", "motif_bank.json",
                 "lessons_learned.jsonl", "chapter_titles.json")
        digest = hashlib.sha256()
        for name in files:
            fp = self.novel_dir / "bible" / name
            digest.update(name.encode())
            if fp.exists():
                digest.update(fp.read_bytes())
        return digest.hexdigest()

    def ensure_imported(self, force: bool = False) -> dict:
        """导入 Bible 种子；仅在首次或文件内容变化时同步，保留运行态字段。"""
        signature = self._bible_signature()
        row = self.conn.execute("SELECT value FROM meta WHERE key='bible_signature'").fetchone()
        if not force and row and row[0] == signature:
            return {"skipped": True}
        counts = self.import_bible()
        self.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('bible_signature',?)",
                          (signature,))
        self.conn.commit()
        return counts

    # ------------------------------------------------------------------ init
    def import_bible(self, force: bool = False) -> dict:
        """从 bible/*.json 幂等导入种子数据，回填已生成章节统计。返回各表写入量。"""
        b = self.novel_dir / "bible"
        counts = {}
        if (b / "characters.json").exists():
            data = json.loads((b / "characters.json").read_text(encoding="utf-8"))
            n = 0
            for name, prof in data.get("characters", {}).items():
                self.conn.execute(
                    """INSERT INTO characters(name, role, voice_print, first_chapter,
                         profile_json, updated_chapter)
                       VALUES(?,?,?,?,?,0)
                       ON CONFLICT(name) DO UPDATE SET
                         role=excluded.role, voice_print=excluded.voice_print,
                         profile_json=CASE
                           WHEN COALESCE(characters.updated_chapter, 0) > 0
                           THEN characters.profile_json ELSE excluded.profile_json END""",
                    (name, prof.get("role", ""), prof.get("voice_print", ""),
                     prof.get("first_appearance_chapter"),
                     json.dumps(prof, ensure_ascii=False)))
                n += 1
            counts["characters"] = n
        if (b / "clues.json").exists():
            data = json.loads((b / "clues.json").read_text(encoding="utf-8"))
            n = 0
            for cid, c in data.get("clues", {}).items():
                self.conn.execute(
                    """INSERT INTO clues(id,name,type,description,introduced_ch,
                         intended_reveal_ch,resolved,state_json)
                       VALUES(?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET
                         name=excluded.name, type=excluded.type,
                         description=excluded.description,
                         introduced_ch=excluded.introduced_ch,
                         intended_reveal_ch=excluded.intended_reveal_ch,
                         state_json=CASE WHEN COALESCE(clues.updated_ch, 0) > 0
                           THEN clues.state_json ELSE excluded.state_json END,
                         resolved=CASE WHEN COALESCE(clues.updated_ch, 0) > 0
                           THEN clues.resolved ELSE excluded.resolved END""",
                    (cid, c.get("name", ""), c.get("type", ""),
                     c.get("description", ""), c.get("introduced_chapter"),
                     c.get("intended_reveal_chapter") or c.get("intended_resolution_chapter"),
                     1 if c.get("resolved") else 0,
                     json.dumps(c, ensure_ascii=False)))
                n += 1
            f = 0
            for fid, fs in data.get("active_foreshadowing", {}).items():
                self.conn.execute(
                    """INSERT INTO foreshadowing(id,name,status,planted_ch,payoff_ch,
                         description,hinted_chs,scope,importance,touch_interval,
                         payoff_start_ch,payoff_end_ch)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET
                         name=excluded.name, description=excluded.description,
                         planted_ch=excluded.planted_ch, payoff_ch=excluded.payoff_ch,
                         scope=excluded.scope, importance=excluded.importance,
                         touch_interval=excluded.touch_interval,
                         payoff_start_ch=excluded.payoff_start_ch,
                         payoff_end_ch=excluded.payoff_end_ch""",
                    (fid, fs.get("name", ""), fs.get("status", "pending"),
                     fs.get("introduced_chapter"), fs.get("intended_payoff_chapter"),
                     fs.get("description", ""),
                     json.dumps(fs.get("hinted_chapters") or
                                ([fs.get("introduced_chapter")] if fs.get("introduced_chapter") else [])),
                     fs.get("scope"), fs.get("importance"), fs.get("touch_interval"),
                     fs.get("payoff_start_chapter"), fs.get("payoff_end_chapter")))
                f += 1
            counts["clues"], counts["foreshadowing"] = n, f
        if (b / "motif_bank.json").exists():
            data = json.loads((b / "motif_bank.json").read_text(encoding="utf-8"))
            n = 0
            for m in data.get("motifs", []):
                self.conn.execute(
                    """INSERT INTO motifs(id,name,description,used_chs) VALUES(?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                         description=excluded.description""",
                    (m.get("id", m.get("name", "")), m.get("name", ""),
                     m.get("description", ""),
                     json.dumps(m.get("used_in_chapters", []))))
                n += 1
            counts["motifs"] = n
        if (b / "lessons_learned.jsonl").exists():
            n = 0
            for line in (b / "lessons_learned.jsonl").read_text(encoding="utf-8").strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self.conn.execute(
                    "INSERT OR IGNORE INTO lessons(chapter,issue,fix,source) VALUES(?,?,?,?)",
                    (e.get("chapter"), e.get("issue", ""), e.get("fix", ""),
                     e.get("source", "user")))
                n += 1
            counts["lessons"] = n
        # 章节统计回填（字数/标题；不覆盖已有 LLM 评分记录）
        titles = {}
        tf = b / "chapter_titles.json"
        if tf.exists():
            td = json.loads(tf.read_text(encoding="utf-8"))
            for v in td.get("volumes", {}).values():
                for k, t in v.get("chapters", {}).items():
                    titles[int(k)] = t
        n = 0
        gen = chapter_files(self.novel_dir / "generated")
        for fp in gen:
            ch = parse_chapter_number(fp)
            text = fp.read_text(encoding="utf-8")
            self.conn.execute(
                """INSERT INTO chapter_log(chapter,title,words,status)
                   VALUES(?,?,?,'generated')
                   ON CONFLICT(chapter) DO UPDATE SET
                     words=excluded.words,
                     title=COALESCE(chapter_log.title, excluded.title)""",
                (ch, titles.get(ch, ""), len(text)))
            n += 1
        counts["chapter_log"] = n
        self.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('bible_signature',?)",
                          (self._bible_signature(),))
        self.conn.commit()
        return counts

    # ---------------------------------------------------------------- writes
    def log_chapter(self, chapter, title=None, words=None, reader_score=None,
                    would_continue=None, violations=None, status="generated"):
        self.conn.execute(
            """INSERT INTO chapter_log(chapter,title,words,reader_score,
                 would_continue,violations,status)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(chapter) DO UPDATE SET
                 title=COALESCE(excluded.title, chapter_log.title),
                 words=COALESCE(excluded.words, chapter_log.words),
                 reader_score=COALESCE(excluded.reader_score, chapter_log.reader_score),
                 would_continue=COALESCE(excluded.would_continue, chapter_log.would_continue),
                 violations=COALESCE(excluded.violations, chapter_log.violations),
                 status=excluded.status""",
            (chapter, title, words, reader_score,
             None if would_continue is None else int(bool(would_continue)),
             violations, status))
        self.conn.commit()

    def delete_style_hits(self, chapter, commit=True):
        self.conn.execute("DELETE FROM style_hits WHERE chapter=?", (chapter,))
        if commit:
            self.conn.commit()

    def add_style_hits(self, rows, commit=True):
        self.conn.executemany(
            "INSERT INTO style_hits(chapter,category,pattern,count) VALUES(?,?,?,?) "
            "ON CONFLICT(chapter,category,pattern) DO UPDATE SET count=excluded.count",
            rows)
        if commit:
            self.conn.commit()

    def add_facts(self, chapter, facts: list, commit=True):
        n = 0
        for f in facts:
            self.conn.execute(
                "INSERT OR IGNORE INTO chapter_facts(chapter,kind,subject,content,scene_id) "
                "VALUES(?,?,?,?,?)",
                (chapter, f.get("kind", "plot"), f.get("subject", ""),
                 f.get("content", ""), f.get("scene_id")))
            n += 1
        if commit:
            self.conn.commit()
        return n

    def add_character_state(self, chapter, character, state: dict, commit=True):
        self.conn.execute(
            "INSERT INTO character_states(chapter,character,state_json) VALUES(?,?,?) "
            "ON CONFLICT(chapter,character) DO UPDATE SET state_json=excluded.state_json",
            (chapter, character, json.dumps(state, ensure_ascii=False)))
        self.conn.execute(
            "UPDATE characters SET updated_chapter=?, profile_json="
            "COALESCE(profile_json,'{}') WHERE name=?", (chapter, character))
        if commit:
            self.conn.commit()

    def replace_chapter_derivatives(self, chapter: int, facts: list, states: dict,
                                    summary: str, content_hash: str,
                                    commit: bool = True):
        self.conn.execute("DELETE FROM chapter_facts WHERE chapter=?", (chapter,))
        self.conn.execute("DELETE FROM character_states WHERE chapter=?", (chapter,))
        self.conn.execute("DELETE FROM chapter_summaries WHERE chapter=?", (chapter,))
        self.add_facts(chapter, facts or [], commit=False)
        for character, state in (states or {}).items():
            self.add_character_state(chapter, character, state, commit=False)
        self.conn.execute(
            "INSERT INTO chapter_summaries(chapter,summary,content_hash) VALUES(?,?,?)",
            (chapter, summary, content_hash),
        )
        if commit:
            self.conn.commit()

    def clear_chapter_derivatives(self, chapter: int, commit: bool = True):
        self.conn.execute("DELETE FROM chapter_facts WHERE chapter=?", (chapter,))
        self.conn.execute("DELETE FROM character_states WHERE chapter=?", (chapter,))
        self.conn.execute("DELETE FROM chapter_summaries WHERE chapter=?", (chapter,))
        if commit:
            self.conn.commit()

    def invalidate_from(self, chapter: int):
        with self.conn:
            self.conn.execute("DELETE FROM chapter_facts WHERE chapter>=?", (chapter,))
            self.conn.execute("DELETE FROM character_states WHERE chapter>=?", (chapter,))
            self.conn.execute("DELETE FROM chapter_summaries WHERE chapter>=?", (chapter,))
            self.conn.execute(
                "UPDATE chapter_log SET status='knowledge_stale' WHERE chapter>=?",
                (chapter,),
            )

    def recent_summaries(self, before_chapter: int, limit: int = 10) -> list:
        rows = self.conn.execute(
            "SELECT chapter,summary,content_hash,updated_at FROM chapter_summaries "
            "WHERE chapter<? ORDER BY chapter DESC LIMIT ?",
            (before_chapter, limit),
        ).fetchall()
        return list(reversed(rows))

    def upsert_character(self, name, profile: dict, chapter=None, commit=True):
        self.conn.execute(
            """INSERT INTO characters(name, role, voice_print, first_chapter, profile_json, updated_chapter)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET
                 profile_json=excluded.profile_json,
                 role=excluded.role, voice_print=excluded.voice_print,
                 first_chapter=excluded.first_chapter,
                 updated_chapter=COALESCE(excluded.updated_chapter, characters.updated_chapter)""",
            (name, profile.get("role", ""), profile.get("voice_print", ""),
             profile.get("first_appearance_chapter"),
             json.dumps(profile, ensure_ascii=False), chapter))
        if commit:
            self.conn.commit()

    def hint_foreshadow(self, fid, chapter, status=None, commit=True):
        row = self.conn.execute(
            "SELECT hinted_chs FROM foreshadowing WHERE id=?", (fid,)).fetchone()
        if not row:
            return 0
        chs = json.loads(row["hinted_chs"] or "[]")
        if chapter not in chs:
            chs.append(chapter)
        cursor = self.conn.execute(
            "UPDATE foreshadowing SET hinted_chs=?, status=COALESCE(?,status) WHERE id=?",
            (json.dumps(chs), status, fid),
        )
        if commit:
            self.conn.commit()
        return cursor.rowcount

    def resolve_foreshadow(self, fid, chapter, commit=True):
        cursor = self.conn.execute(
            "UPDATE foreshadowing SET status='resolved', resolved_ch=? WHERE id=?",
            (chapter, fid))
        if commit:
            self.conn.commit()
        return cursor.rowcount

    def retire_foreshadow(self, fid, chapter, commit=True):
        cursor = self.conn.execute(
            "UPDATE foreshadowing SET status='retired', resolved_ch=? WHERE id=?",
            (chapter, fid))
        if commit:
            self.conn.commit()
        return cursor.rowcount

    def reschedule_foreshadow(self, fid, data: dict, commit=True):
        cursor = self.conn.execute(
            """UPDATE foreshadowing SET payoff_ch=COALESCE(?,payoff_ch),
                   payoff_start_ch=COALESCE(?,payoff_start_ch),
                   payoff_end_ch=COALESCE(?,payoff_end_ch),
                   touch_interval=COALESCE(?,touch_interval) WHERE id=?""",
            (data.get("intended_payoff_chapter"), data.get("payoff_start_chapter"),
             data.get("payoff_end_chapter"), data.get("touch_interval"), fid),
        )
        if commit:
            self.conn.commit()
        return cursor.rowcount

    def upsert_clue(self, cid, data: dict, chapter=None, commit=True):
        state = data.get("state", data)
        self.conn.execute(
            """INSERT INTO clues(id,name,type,description,introduced_ch,
                   intended_reveal_ch,resolved,state_json,updated_ch)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name, type=excluded.type,
                 description=excluded.description,
                 introduced_ch=excluded.introduced_ch,
                 intended_reveal_ch=excluded.intended_reveal_ch,
                 resolved=excluded.resolved, state_json=excluded.state_json,
                 updated_ch=COALESCE(excluded.updated_ch, clues.updated_ch)""",
            (cid, data.get("name", ""), data.get("type", ""),
             data.get("description", ""), data.get("introduced_chapter"),
             data.get("intended_reveal_chapter") or data.get("intended_resolution_chapter"),
             1 if data.get("resolved") else 0,
             json.dumps(state, ensure_ascii=False), chapter))
        if commit:
            self.conn.commit()

    def update_clue(self, cid, state: dict, chapter):
        cursor = self.conn.execute(
            """UPDATE clues SET state_json=?, resolved=?, updated_ch=? WHERE id=?""",
            (json.dumps(state, ensure_ascii=False), 1 if state.get("resolved") else 0,
             chapter, cid))
        self.conn.commit()
        return cursor.rowcount

    def upsert_foreshadow(self, fid, data: dict, commit=True):
        hinted = data.get("hinted_chapters")
        if hinted is None:
            introduced = data.get("introduced_chapter")
            hinted = [introduced] if introduced else []
        cursor = self.conn.execute(
            """INSERT INTO foreshadowing(id,name,status,planted_ch,payoff_ch,
                   resolved_ch,description,hinted_chs,scope,importance,touch_interval,
                   payoff_start_ch,payoff_end_ch)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name, status=excluded.status,
                 planted_ch=excluded.planted_ch, payoff_ch=excluded.payoff_ch,
                 resolved_ch=excluded.resolved_ch, description=excluded.description,
                 hinted_chs=excluded.hinted_chs, scope=excluded.scope,
                 importance=excluded.importance, touch_interval=excluded.touch_interval,
                 payoff_start_ch=excluded.payoff_start_ch,
                 payoff_end_ch=excluded.payoff_end_ch""",
            (fid, data.get("name", ""), data.get("status", "pending"),
             data.get("introduced_chapter"), data.get("intended_payoff_chapter"),
             data.get("resolved_chapter"), data.get("description", ""),
             json.dumps(hinted), data.get("scope"), data.get("importance"),
             data.get("touch_interval"), data.get("payoff_start_chapter"),
             data.get("payoff_end_chapter")))
        if commit:
            self.conn.commit()
        return cursor.rowcount

    def create_foreshadow(self, fid, data: dict, commit=True):
        if self.conn.execute(
            "SELECT 1 FROM foreshadowing WHERE id=?", (fid,)
        ).fetchone():
            return 0
        return self.upsert_foreshadow(fid, data, commit=commit)

    def add_lesson(self, chapter, issue, fix, source="user"):
        self.conn.execute(
            "INSERT OR IGNORE INTO lessons(chapter,issue,fix,source) VALUES(?,?,?,?)",
            (chapter, issue, fix, source))
        self.conn.commit()

    def mark_motif_used(self, mid, chapter):
        row = self.conn.execute("SELECT used_chs FROM motifs WHERE id=?", (mid,)).fetchone()
        if not row:
            return
        chs = json.loads(row["used_chs"] or "[]")
        if chapter not in chs:
            chs.append(chapter)
            self.conn.execute("UPDATE motifs SET used_chs=? WHERE id=?",
                              (json.dumps(chs), mid))
            self.conn.commit()

    # ----------------------------------------------------------------- reads
    def recent_states(self, characters: list, before_ch: int, per_char=3) -> list:
        out = []
        for c in characters:
            rows = self.conn.execute(
                "SELECT * FROM character_states WHERE character=? AND chapter<? "
                "ORDER BY chapter DESC LIMIT ?", (c, before_ch, per_char)).fetchall()
            out.extend(reversed(rows))
        return out

    def open_foreshadowing(self, current_ch: int, stale_after=30) -> dict:
        rows = self.conn.execute(
            "SELECT * FROM foreshadowing WHERE status NOT IN ('resolved','retired')"
        ).fetchall()
        stale, normal, overdue_payoff = [], [], []
        for r in rows:
            chs = json.loads(r["hinted_chs"] or "[]")
            last = max(chs) if chs else (r["planted_ch"] or 0)
            gap = current_ch - last
            item = dict(r)
            item["days_dark"] = gap
            interval = r["touch_interval"] if r["touch_interval"] is not None else stale_after
            payoff_deadline = r["payoff_end_ch"] or r["payoff_ch"]
            if payoff_deadline and current_ch >= payoff_deadline:
                overdue_payoff.append(item)
            elif gap > interval:
                stale.append(item)
            else:
                normal.append(item)
        return {"stale": stale, "overdue_to_payoff": overdue_payoff,
                "normal": normal}

    def search_facts(self, keywords: list, before_ch: int, limit=25) -> list:
        if not keywords:
            return []
        conds = " OR ".join(["content LIKE ? OR subject LIKE ?"] * len(keywords))
        params = []
        for k in keywords:
            params += [f"%{k}%", f"%{k}%"]
        params.append(before_ch)
        return self.conn.execute(
            f"SELECT * FROM chapter_facts WHERE ({conds}) AND chapter<? "
            f"ORDER BY chapter DESC LIMIT {int(limit)}", params).fetchall()

    def top_style_hits(self, before_ch=None, n=8) -> list:
        q = ("SELECT category, pattern, SUM(count) AS total FROM style_hits ")
        params = []
        if before_ch:
            q += "WHERE chapter<? "
            params = [before_ch]
        q += "GROUP BY category, pattern ORDER BY total DESC LIMIT ?"
        params.append(n)
        return self.conn.execute(q, params).fetchall()

    def lessons_recent(self, n=5) -> list:
        return self.conn.execute(
            "SELECT * FROM lessons ORDER BY id DESC LIMIT ?", (n,)).fetchall()

    def stats(self) -> dict:
        def one(sql, args=()):
            r = self.conn.execute(sql, args).fetchone()
            return r[0] if r and r[0] is not None else 0
        return {
            "db_bytes": self.path.stat().st_size if self.path.exists() else 0,
            "characters": one("SELECT COUNT(*) FROM characters"),
            "facts": one("SELECT COUNT(*) FROM chapter_facts"),
            "clues": one("SELECT COUNT(*) FROM clues"),
            "foreshadow_total": one("SELECT COUNT(*) FROM foreshadowing"),
            "foreshadow_resolved": one(
                "SELECT COUNT(*) FROM foreshadowing WHERE status='resolved'"),
            "lessons": one("SELECT COUNT(*) FROM lessons"),
            "chapters_logged": one("SELECT COUNT(*) FROM chapter_log"),
            "style_hits": one("SELECT COALESCE(SUM(count),0) FROM style_hits"),
        }
