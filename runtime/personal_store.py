"""Small durable personal inbox. Separate from extracted/retrieval memory."""
import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


class PersonalStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS memories(id TEXT PRIMARY KEY, content TEXT, created TEXT);
              CREATE TABLE IF NOT EXISTS reminders(id TEXT PRIMARY KEY, text TEXT, due TEXT, status TEXT);
              CREATE TABLE IF NOT EXISTS reminder_announcements(reminder_id TEXT PRIMARY KEY, claimed_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY, kind TEXT, label TEXT, payload TEXT, created TEXT, undone INTEGER DEFAULT 0);
            ''')
            if 'updated' not in {r['name'] for r in db.execute('PRAGMA table_info(memories)')}:
                db.execute('ALTER TABLE memories ADD COLUMN updated TEXT')
        os.chmod(self.path, 0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA secure_delete=ON')
        return db

    @staticmethod
    def record(db, kind, label, payload):
        db.execute('INSERT INTO actions(id,kind,label,payload,created) VALUES(?,?,?,?,?)',
                   (uuid.uuid4().hex, kind, label, json.dumps(payload), datetime.now(timezone.utc).isoformat()))

    def remember(self, content):
        content = content.strip()
        if not content or len(content) > 12000:
            raise ValueError('Memory must contain 1–12000 characters')
        item = dict(id=uuid.uuid4().hex, content=content, created=datetime.now(timezone.utc).isoformat())
        with self.connect() as db:
            db.execute('INSERT INTO memories(id,content,created) VALUES(:id,:content,:created)', item)
            self.record(db, 'memory_add', 'Saved a personal memory', {'id': item['id']})
        return item

    def memories(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM memories ORDER BY created DESC')]

    def edit_memory(self,item_id,content):
        content=content.strip()
        if not content or len(content)>12000:raise ValueError('Memory must contain 1–12000 characters')
        now=datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            if not db.execute('UPDATE memories SET content=?,updated=? WHERE id=?',(content,now,item_id)).rowcount:
                raise ValueError('Memory not found')
            self.record(db,'memory_edit','Updated a personal memory',{'id':item_id})
        return {'id':item_id,'content':content,'updated':now}

    def recall(self,query,limit=5):
        terms=set(re.findall(r'[a-z0-9]{2,}',str(query).lower()))
        if not terms:return []
        matches=[]
        for item in self.memories():
            words=set(re.findall(r'[a-z0-9]{2,}',item['content'].lower()))
            score=len(terms & words)
            if score:matches.append((score,item))
        matches.sort(key=lambda pair:(pair[0],pair[1].get('updated') or pair[1]['created']),reverse=True)
        return [{**item,'content':item['content'][:1200],'source':'explicit personal memory'} for _,item in matches[:max(1,min(5,int(limit)))]]

    def forget(self, item_id):
        with self.connect() as db:
            if not db.execute('DELETE FROM memories WHERE id=?', (item_id,)).rowcount:
                raise ValueError('Memory not found')
            self.record(db, 'forgot', 'Forgot a personal memory', {})

    def add_reminder(self, text, due):
        parsed = datetime.fromisoformat(due.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed <= datetime.now(timezone.utc):
            raise ValueError('Use a future date and time including its timezone')
        text = text.strip()
        if not text or len(text) > 2000:
            raise ValueError('Reminder must contain 1–2000 characters')
        item = dict(id=uuid.uuid4().hex, text=text, due=parsed.astimezone(timezone.utc).isoformat(), status='pending')
        with self.connect() as db:
            db.execute('INSERT INTO reminders VALUES(:id,:text,:due,:status)', item)
            self.record(db, 'reminder_add', 'Added a reminder', {'id': item['id']})
        return item

    def reminders(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM reminders ORDER BY due')]

    def deliver_due(self, now=None):
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        with self.connect() as db:
            # Serialize the read and update so two scheduler ticks cannot deliver twice.
            db.execute('BEGIN IMMEDIATE')
            items = [dict(r) for r in db.execute("SELECT * FROM reminders WHERE status='pending' AND due<=?", (now,))]
            db.execute("UPDATE reminders SET status='delivered' WHERE status='pending' AND due<=?", (now,))
        return items

    def claim_due_announcements(self):
        # Only current reminders may interrupt. Old items remain visible in the inbox.
        now=datetime.now(timezone.utc)
        cutoff=(now-timedelta(minutes=2)).isoformat()
        current=now.isoformat()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE reminders SET status='delivered' WHERE status='pending' AND due<=?",(current,))
            rows=[dict(r) for r in db.execute(
                "SELECT r.* FROM reminders r WHERE r.status='delivered' AND r.due>? AND r.due<=? "
                "AND NOT EXISTS (SELECT 1 FROM reminder_announcements a WHERE a.reminder_id=r.id) ORDER BY r.due",
                (cutoff,current))]
            # Claim before output, so refreshes and simultaneous tabs cannot replay speech.
            db.executemany('INSERT INTO reminder_announcements(reminder_id,claimed_at) VALUES(?,?)',
                           [(r['id'],current) for r in rows])
        return rows

    def dismiss(self, item_id):
        with self.connect() as db:
            if not db.execute("UPDATE reminders SET status='dismissed' WHERE id=?", (item_id,)).rowcount:
                raise ValueError('Reminder not found')

    def actions(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT id,kind,label,created,undone FROM actions ORDER BY rowid DESC LIMIT 100')]

    def undo(self, action_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM actions WHERE id=?', (action_id,)).fetchone()
            if not row or row['undone']:
                raise ValueError('Action not found or already undone')
            payload = json.loads(row['payload'])
            if row['kind'] == 'memory_add':
                db.execute('DELETE FROM memories WHERE id=?', (payload['id'],))
            elif row['kind'] == 'reminder_add':
                reminder = db.execute('SELECT status FROM reminders WHERE id=?', (payload['id'],)).fetchone()
                if not reminder or reminder['status'] != 'pending':
                    raise ValueError('Delivered reminders cannot be unsent')
                db.execute('DELETE FROM reminders WHERE id=?', (payload['id'],))
            else:
                raise ValueError('This action cannot be undone')
            db.execute('UPDATE actions SET undone=1 WHERE id=?', (action_id,))
        return {'undone': True}
