"""Outbound-only, free ntfy alerts. Never sends notes or arbitrary reminder text."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import fcntl
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

RUNTIME=Path.home()/'.openjarvis/runtime'
CONFIG=RUNTIME/'phone-alerts.json'
DATABASE=Path.home()/'.openjarvis/personal.db'
LEDGER=RUNTIME/'phone-alert-deliveries.sqlite'
STATUS=RUNTIME/'phone-alert-status.json'
# Fixed, non-sensitive notification bodies. Never forward r.text or note content.
MESSAGES={}  # Add generic, user-approved notification bodies for your own schedule IDs.


def now():return datetime.now(timezone.utc)

def save(path,data):
    temp=path.with_name(path.name+'.'+secrets.token_hex(5)+'.tmp')
    fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,'w') as file:json.dump(data,file)
        temp.replace(path)
    finally:temp.unlink(missing_ok=True)


def config():
    value=json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    topic=value.get('topic','')
    if topic and not re.fullmatch(r'jarvis-[a-zA-Z0-9_-]{32}',topic):raise ValueError('Invalid phone-alert pairing configuration.')
    return value


def setup():
    if not CONFIG.exists():
        save(CONFIG,{'topic':'jarvis-'+secrets.token_urlsafe(24),'enabled':False,'paired':False,
                     'created_at':now().isoformat(),'privacy':'generic_schedule_alerts_only'})
    return config()


def set_enabled(enabled):
    value=setup();value['enabled']=bool(enabled)
    if enabled:value.update(paired=True,enabled_at=now().isoformat())
    save(CONFIG,value)


def connection():
    db=sqlite3.connect(LEDGER,timeout=15);db.row_factory=sqlite3.Row
    db.execute('''CREATE TABLE IF NOT EXISTS deliveries(
      reminder_id TEXT PRIMARY KEY,schedule_id TEXT NOT NULL,state TEXT NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0,next_try REAL NOT NULL DEFAULT 0,
      receipt_id TEXT,updated TEXT NOT NULL)''')
    os.chmod(LEDGER,0o600)
    return db


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def send(topic,schedule_id):
    title,body=MESSAGES[schedule_id]
    request=Request('https://ntfy.sh/'+topic,data=body.encode(),method='POST',
        headers={'Title':title,'Priority':'default','Content-Type':'text/plain; charset=utf-8',
                 'User-Agent':'Jarvis-Phone-Alerts/1.0'})
    # No proxy credential leakage and no redirect to an unexpected destination.
    opener=build_opener(ProxyHandler({}),NoRedirect())
    with opener.open(request,timeout=12) as response:
        data=json.loads(response.read(65536))
        if response.status!=200 or data.get('event')!='message' or not data.get('id'):
            raise ValueError('The notification service did not return an acceptance receipt.')
        return data['id']


def tick():
    c=config()
    if not c.get('enabled'):
        return {'state':'awaiting_phone_setup' if not c.get('paired') else 'disabled','message':'Phone subscription is not yet confirmed.'}
    current=now();cutoff=max(current-timedelta(minutes=2),datetime.fromisoformat(c['enabled_at']))
    uri='file:'+str(DATABASE)+'?mode=ro'
    with sqlite3.connect(uri,uri=True,timeout=15) as source:
        source.row_factory=sqlite3.Row
        rows=source.execute('''SELECT r.id,o.schedule_id FROM reminders r
            JOIN jarvis_daily_occurrences o ON o.reminder_id=r.id
            JOIN jarvis_daily_schedules s ON s.id=o.schedule_id
            WHERE s.active=1 AND r.status IN ('pending','delivered') AND r.due>? AND r.due<=?
            AND o.schedule_id IN ('personal-morning-routine','example-evening') ORDER BY r.due''',
            (cutoff.isoformat(),current.isoformat())).fetchall()
    outcome={'state':'ready','message':'Waiting for the next scheduled reminder.'}
    with connection() as db:
        # A crashed/in-flight send may have reached the service: do not replay it.
        db.execute("UPDATE deliveries SET state='uncertain',updated=? WHERE state='sending'",(current.isoformat(),))
        previous=db.execute("SELECT state FROM deliveries WHERE state IN ('failed','uncertain') ORDER BY updated DESC LIMIT 1").fetchone()
        if previous:outcome={'state':'warning','message':'A previous alert was not confirmed. Check the phone-alert delivery history.'}
        for row in rows:
            record=db.execute('SELECT * FROM deliveries WHERE reminder_id=?',(row['id'],)).fetchone()
            if record and (record['state']!='retry' or record['next_try']>time.time()):continue
            attempts=(record['attempts'] if record else 0)+1
            db.execute('''INSERT INTO deliveries(reminder_id,schedule_id,state,attempts,updated)
                VALUES(?,?,'sending',?,?) ON CONFLICT(reminder_id) DO UPDATE SET
                state='sending',attempts=excluded.attempts,updated=excluded.updated''',
                (row['id'],row['schedule_id'],attempts,current.isoformat()))
            db.commit()
            try:
                receipt=send(c['topic'],row['schedule_id'])
                db.execute("UPDATE deliveries SET state='accepted',receipt_id=?,updated=? WHERE reminder_id=?",(receipt,now().isoformat(),row['id']))
                outcome={'state':'ready','message':'Notification service accepted an alert. Phone display has not been verified.'}
            except HTTPError as error:
                retry=error.code==429 and attempts<3
                db.execute('UPDATE deliveries SET state=?,next_try=?,updated=? WHERE reminder_id=?',
                    ('retry' if retry else 'failed',time.time()+30,now().isoformat(),row['id']))
                outcome={'state':'warning','message':'Notification service rate limit.' if retry else 'Notification service rejected an alert.'}
            except (URLError,TimeoutError,ValueError,OSError):
                db.execute("UPDATE deliveries SET state='uncertain',updated=? WHERE reminder_id=?",(now().isoformat(),row['id']))
                outcome={'state':'warning','message':'Alert acceptance could not be confirmed. It will not be resent to avoid duplicates.'}
            db.commit()
    return outcome


def ensure_worker():
    with (RUNTIME/'phone-alerts.log').open('a') as log:
        os.chmod(log.name,0o600)
        subprocess.Popen([sys.executable,str(RUNTIME/'phone_alerts.py'),'--worker'],
            cwd=RUNTIME,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)


def worker():
    with (RUNTIME/'phone-alerts.lock').open('a') as lock:
        os.chmod(lock.name,0o600)
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        while True:
            try:status=tick()
            except Exception:status={'state':'error','message':'Phone-alert sender could not read its schedule or configuration.'}
            save(STATUS,{**status,'pid':os.getpid(),'last_tick':now().isoformat()})
            time.sleep(5)


if __name__=='__main__':
    if '--worker' in sys.argv:worker()
    elif '--enable' in sys.argv:set_enabled(True);ensure_worker();print('Phone alerts enabled. No trial alert sent.')
    elif '--disable' in sys.argv:set_enabled(False);print('Phone alerts disabled.')
    elif '--setup' in sys.argv:setup();ensure_worker();print('Phone sender installed; awaiting iPhone pairing. No alert sent.')
    else:
        c=config();print(json.dumps({'enabled':c.get('enabled',False),'paired':c.get('paired',False),
             'status':json.loads(STATUS.read_text()) if STATUS.exists() else None},indent=2))
