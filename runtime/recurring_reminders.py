"""Deterministic local daily reminders; standard library, no model/API calls."""
from datetime import datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import fcntl
import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
import uuid

ROOT = Path.home()/'.openjarvis'
RUNTIME = ROOT/'runtime'
DATABASE = ROOT/'personal.db'
TZ = ZoneInfo('America/New_York')
SCHEDULES = ()  # Configure your own schedules; no personal reminders are shipped.


def connect():
    db=sqlite3.connect(DATABASE, timeout=20)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def initialize():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS jarvis_daily_schedules(
            id TEXT PRIMARY KEY, name TEXT NOT NULL, text TEXT NOT NULL,
            hour INTEGER NOT NULL, minute INTEGER NOT NULL,
            timezone TEXT NOT NULL, starts_on TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jarvis_daily_occurrences(
            schedule_id TEXT NOT NULL, local_date TEXT NOT NULL,
            reminder_id TEXT NOT NULL UNIQUE, created TEXT NOT NULL,
            PRIMARY KEY(schedule_id,local_date)
        );
        ''')


def configure():
    now=datetime.now(TZ)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for schedule in SCHEDULES:
            today=datetime.combine(now.date(),clock_time(schedule['hour'],schedule['minute']),TZ)
            start=(now.date() if today>now else now.date()+timedelta(days=1)).isoformat()
            # Stable ids make repeated activation idempotent; preserve creation/start dates.
            db.execute('''INSERT INTO jarvis_daily_schedules
                (id,name,text,hour,minute,timezone,starts_on,active,created)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,text=excluded.text,hour=excluded.hour,minute=excluded.minute,
                timezone=excluded.timezone,active=1''',
                (schedule['id'],schedule['name'],schedule['text'],schedule['hour'],schedule['minute'],TZ.key,start,1,now.astimezone(timezone.utc).isoformat()))


def reconcile():
    now=datetime.now(timezone.utc)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        schedules=db.execute('SELECT * FROM jarvis_daily_schedules WHERE active=1').fetchall()
        for schedule in schedules:
            tz=ZoneInfo(schedule['timezone']); local_now=now.astimezone(tz)
            day=max(local_now.date(),datetime.fromisoformat(schedule['starts_on']).date())
            due=datetime.combine(day,clock_time(schedule['hour'],schedule['minute']),tz)
            if due<=local_now:
                day+=timedelta(days=1)
                due=datetime.combine(day,clock_time(schedule['hour'],schedule['minute']),tz)
            known=db.execute('SELECT reminder_id FROM jarvis_daily_occurrences WHERE schedule_id=? AND local_date=?',(schedule['id'],day.isoformat())).fetchone()
            if known:
                continue
            # Adopt an existing identical pending reminder rather than duplicate it.
            utc_due=due.astimezone(timezone.utc).isoformat()
            existing=db.execute("SELECT id FROM reminders WHERE text=? AND due=? AND status='pending' LIMIT 1",(schedule['text'],utc_due)).fetchone()
            reminder_id=existing['id'] if existing else uuid.uuid4().hex
            if not existing:
                db.execute('INSERT INTO reminders(id,text,due,status) VALUES(?,?,?,?)',(reminder_id,schedule['text'],utc_due,'pending'))
                db.execute('INSERT INTO actions(id,kind,label,payload,created) VALUES(?,?,?,?,?)',
                    (uuid.uuid4().hex,'reminder_add','Scheduled daily '+schedule['name'],json.dumps({'id':reminder_id,'schedule_id':schedule['id']}),now.isoformat()))
            db.execute('INSERT INTO jarvis_daily_occurrences(schedule_id,local_date,reminder_id,created) VALUES(?,?,?,?)',
                (schedule['id'],day.isoformat(),reminder_id,now.isoformat()))


def receipts():
    with connect() as db:
        return [dict(row) for row in db.execute('''SELECT s.id,s.name,s.hour,s.minute,s.timezone,s.active,
            r.id AS reminder_id,r.text,r.due,r.status
            FROM jarvis_daily_schedules s JOIN jarvis_daily_occurrences o ON s.id=o.schedule_id
            JOIN reminders r ON r.id=o.reminder_id WHERE s.active=1 AND r.status='pending'
            ORDER BY r.due''')]


def ensure_worker():
    log_path=RUNTIME/'recurring-reminders.log'
    with log_path.open('a') as log:
        subprocess.Popen([sys.executable,str(RUNTIME/'recurring_reminders.py'),'--worker'],
            cwd=RUNTIME,stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True)


def worker():
    # Only one worker survives, including across backend restarts.
    with (RUNTIME/'recurring-reminders.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        (RUNTIME/'recurring-reminders.pid').write_text(str(os.getpid()))
        logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
        initialize()
        logging.info('Daily reminder worker running; timezone %s',TZ.key)
        while True:
            try:
                reconcile()
                state={'pid':os.getpid(),'last_tick':datetime.now(timezone.utc).isoformat(),'status':'running'}
            except Exception:
                logging.exception('Reminder scheduling failed; will retry')
                state={'pid':os.getpid(),'last_tick':datetime.now(timezone.utc).isoformat(),'status':'error'}
            temp=RUNTIME/'recurring-reminders-status.tmp'
            temp.write_text(json.dumps(state));temp.replace(RUNTIME/'recurring-reminders-status.json')
            time.sleep(5)


if __name__=='__main__':
    if '--worker' in sys.argv:worker()
    elif '--activate' in sys.argv:
        initialize();configure();reconcile();ensure_worker()
        print(json.dumps(receipts(),indent=2))
    else:
        print(json.dumps(receipts(),indent=2))
