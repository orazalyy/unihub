"""Persistent community features. Loaded by server.py; standard library only."""
import json, re, time, datetime, hashlib, hmac, os, base64, secrets, smtplib, sys
from email.message import EmailMessage
s = None
KINDS = {'students','roommates','events','lost','opportunities','discounts','clubs','groups'}

def init(c):
    for table, columns in {'users': {'bio': "TEXT NOT NULL DEFAULT ''", 'interests': "TEXT NOT NULL DEFAULT ''", 'community': "TEXT NOT NULL DEFAULT ''", 'email_verified_at': 'INTEGER', 'role': "TEXT NOT NULL DEFAULT 'student'"}, 'products': {'image': "TEXT NOT NULL DEFAULT ''", 'status': "TEXT NOT NULL DEFAULT 'Available'"}}.items():
        existing = {r[1] for r in c.execute('PRAGMA table_info('+table+')')}
        for name, spec in columns.items():
            if name not in existing: c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {spec}')
    c.executescript('''
    CREATE TABLE IF NOT EXISTS entries(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,university TEXT NOT NULL,payload TEXT NOT NULL,created_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS reactions(user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,PRIMARY KEY(user_id,post_id));
    CREATE TABLE IF NOT EXISTS comments(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,text TEXT NOT NULL,created_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS follows(user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,target_id INTEGER REFERENCES users(id) ON DELETE CASCADE,PRIMARY KEY(user_id,target_id),CHECK(user_id!=target_id));
    CREATE TABLE IF NOT EXISTS responses(user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,entry_id INTEGER REFERENCES entries(id) ON DELETE CASCADE,status TEXT NOT NULL,PRIMARY KEY(user_id,entry_id));
    CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,sender_id INTEGER REFERENCES users(id) ON DELETE CASCADE,recipient_id INTEGER REFERENCES users(id) ON DELETE CASCADE,text TEXT NOT NULL,created_at INTEGER NOT NULL,read_at INTEGER,CHECK(sender_id!=recipient_id));
    CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,text TEXT NOT NULL,href TEXT NOT NULL,created_at INTEGER NOT NULL,read_at INTEGER);
    CREATE TABLE IF NOT EXISTS email_codes(user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,email TEXT NOT NULL,code_hash TEXT NOT NULL,expires_at INTEGER NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,sent_at INTEGER NOT NULL,window_start INTEGER NOT NULL,sends INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY,post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,reason TEXT NOT NULL,created_at INTEGER NOT NULL,UNIQUE(post_id,user_id));
    CREATE TABLE IF NOT EXISTS moderation_log(id INTEGER PRIMARY KEY,admin_id INTEGER REFERENCES users(id) ON DELETE SET NULL,action TEXT NOT NULL,target_kind TEXT NOT NULL,target_id INTEGER NOT NULL,author_id INTEGER REFERENCES users(id) ON DELETE SET NULL,excerpt TEXT NOT NULL,reason TEXT NOT NULL,created_at INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS messages_recipient ON messages(recipient_id,id);
    CREATE INDEX IF NOT EXISTS entries_kind ON entries(kind,university);
    CREATE INDEX IF NOT EXISTS notifications_user ON notifications(user_id,id);
    CREATE TABLE IF NOT EXISTS spaces(id INTEGER PRIMARY KEY,name TEXT NOT NULL,building TEXT NOT NULL,capacity INTEGER NOT NULL CHECK(capacity>0),device_id TEXT NOT NULL UNIQUE);
    CREATE TABLE IF NOT EXISTS space_readings(id INTEGER PRIMARY KEY,space_id INTEGER NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,occupancy INTEGER NOT NULL,battery INTEGER NOT NULL,created_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS space_watches(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,space_id INTEGER NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,created_at INTEGER NOT NULL,PRIMARY KEY(user_id,space_id));
    CREATE INDEX IF NOT EXISTS space_readings_time ON space_readings(space_id,created_at);
    CREATE TABLE IF NOT EXISTS login_failures(login TEXT NOT NULL,ip TEXT NOT NULL,at INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS login_failures_key ON login_failures(login,ip);
    ''')
    grant_admins(c)

# Any confirmed address counts as verified for the account, but the public ✓ badge needs a university address.
UNI_DOMAINS={'AITU':('astanait.edu.kz',),'ENU':('enu.kz',),'MNU':('mnu.kz','kazguu.kz'),'Nazarbayev University':('nu.edu.kz',)}

def university_email(email):
    domain=(email or '').rsplit('@',1)[-1].strip().lower()
    return any(domain==d or domain.endswith('.'+d) for ds in UNI_DOMAINS.values() for d in ds) or domain.endswith(('.edu.kz','.edu'))

def has_badge(u): return bool(u['email_verified_at']) and university_email(u['email'])

def public(u):
    return {'id':u['id'],'name':s.short_name(u['first_name'],u['last_name']),'university':u['university'],'bio':u['bio'],'interests':u['interests'],'verified':has_badge(u)}

IMAGE_RE = re.compile(r'data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)')

def image_url(pid, image):
    # Photos are served from their own cacheable URL instead of being inlined into /api/data;
    # the hash changes whenever the photo does, so the long browser cache can never go stale.
    return f'/api/products/{pid}/image?v={hashlib.sha1(image.encode()).hexdigest()[:10]}' if image else ''

def product_image(pid):
    with s.connect() as c:
        r = c.execute('SELECT image FROM products WHERE id=? AND user_id IS NOT NULL', (pid,)).fetchone()
    m = IMAGE_RE.fullmatch(r['image']) if r and r['image'] else None
    return ('image/' + m[1], base64.b64decode(m[2])) if m else None

def notify(c, uid, text, href):
    c.execute('INSERT INTO notifications(user_id,text,href,created_at) VALUES(?,?,?,?)',(uid,text,href,int(time.time())))

FEED_PAGE=30;FEED_MAX=3000

def feed_limit(v):
    """?posts=N from the page: how many feed posts it has loaded, 30 to 3000."""
    return min(max(int(v), FEED_PAGE), FEED_MAX) if str(v).isdigit() else FEED_PAGE

def data(c, me, limit=FEED_PAGE):
    users={u['id']:public(u) for u in c.execute('SELECT * FROM users')}
    following={r[0] for r in c.execute('SELECT target_id FROM follows WHERE user_id=?',(me,))}
    liked={r[0] for r in c.execute('SELECT post_id FROM reactions WHERE user_id=?',(me,))}
    # The feed is sent in pages: the newest `limit` posts (the page asks for 30 more at a time) plus all of
    # the user's own posts for the profile, and only the comments of the posts that are sent.
    rows=c.execute('SELECT * FROM posts WHERE user_id IS NOT NULL ORDER BY sort_key DESC,id DESC LIMIT ?',(limit+1,)).fetchall()
    more=len(rows)>limit;rows=rows[:limit];sent={r['id'] for r in rows}
    rows+=[r for r in c.execute('SELECT * FROM posts WHERE user_id=? ORDER BY sort_key DESC,id DESC',(me,)).fetchall() if r['id'] not in sent]
    ids=[r['id'] for r in rows]
    comments=[dict(r,name=users[r['user_id']]['name'],mine=r['user_id']==me)
              for r in c.execute(f"SELECT * FROM comments WHERE post_id IN ({','.join('?'*len(ids))}) ORDER BY id",ids)] if ids else []
    posts=[]
    for r in rows:
        p=s.post_json(r,me)
        p.update(user_id=r['user_id'],name=users[r['user_id']]['name'],liked=r['id'] in liked,followed=r['user_id'] in following,
                 likes=c.execute('SELECT count(*) FROM reactions WHERE post_id=?',(r['id'],)).fetchone()[0], comments=sum(x['post_id']==r['id'] for x in comments))
        posts.append(p)
    products=[]
    for r in c.execute('SELECT * FROM products WHERE user_id IS NOT NULL ORDER BY id DESC'):
        p=s.product_json(r,me);p.update(user_id=r['user_id'],seller=users[r['user_id']]['name'],image=image_url(r['id'],r['image']),status=r['status']);products.append(p)
    result={k:[] for k in KINDS}
    for r in c.execute('SELECT * FROM entries ORDER BY id DESC'):
        p=json.loads(r['payload']);p.update(id=r['id'],user_id=r['user_id'],university=r['university'],mine=r['user_id']==me,owner=users[r['user_id']]['name'],created_at=r['created_at'])
        if r['kind'] in ('students','roommates'): p.update(name=users[r['user_id']]['name'],tone='blue')
        rs=[dict(x) for x in c.execute('SELECT user_id,status FROM responses WHERE entry_id=?',(r['id'],))]
        p['response']=next((x['status'] for x in rs if x['user_id']==me),'');p['response_count']=len(rs)
        p['participants']=[dict(users[x['user_id']],status=x['status']) for x in rs] if p['mine'] or r['kind'] in ('groups','clubs') else []
        result[r['kind']].append(p)
    messages=[dict(r) for r in c.execute('SELECT * FROM messages WHERE sender_id=? OR recipient_id=? ORDER BY id',(me,me))]
    result.update(posts=posts,posts_more=more,products=products,comments=comments,users=list(users.values()),following=list(following),messages=messages,
                  notifications=[dict(r) for r in c.execute('SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 100',(me,))],
                  counts={u:c.execute('SELECT count(*) FROM users WHERE university=?',(u,)).fetchone()[0] for u in s.UNIVERSITIES},
                  mail_ready=s.MAIL_DEV or bool(os.environ.get('SMTP_USER') and os.environ.get('SMTP_PASSWORD')))
    return result

def text(d,k,limit=500): return s.need_str(d,k,limit)
def choice(d,k,values):
    if d.get(k) not in values: raise s.Bad('Choose a valid '+k,k)
    return d[k]
def number(d,k):
    v=d.get(k)
    if isinstance(v,bool) or not re.fullmatch(r'\d{1,8}',str(v)): raise s.Bad('Enter a whole number for '+k,k)
    v=int(v)
    if v>10000000: raise s.Bad(k+' is too large',k)
    return v

def payload(kind,d):
    fields={'students':['course','year','format','bio'], 'roommates':['district','smoking','pets','lifestyle','sleep','bio'],
            'events':['name','description','date','time','venue','category'], 'lost':['name','description','type','venue'],
            'opportunities':['name','description','category','deadline'], 'discounts':['name','description','code','expires'],
            'clubs':['name','description'],'groups':['name','description','subject','format']}[kind]
    p={k:text(d,k,2000 if k in ('description','bio') else 100) for k in fields}
    if kind in ('students','groups'):p['format']=choice(d,'format',{'Online','Offline'})
    if kind=='students':
        p['subjects']=[x.strip() for x in text(d,'subjects',200).split(',') if x.strip()]
        p['year']=choice(d,'year',{'1st year','2nd year','3rd year','4th year','Graduate'})
    if kind=='roommates':
        p['budget']=number(d,'budget')
        for k,vals in {'smoking':{'Non-smoker','Smoker'},'pets':{'No pets','Pet-friendly'},'lifestyle':{'Quiet','Social','Balanced'},'sleep':{'Early bird','Night owl','Flexible'}}.items():p[k]=choice(d,k,vals)
    if kind=='lost':p['type']=choice(d,'type',{'Lost','Found'})
    for k in ('date','deadline','expires'):
        if k in p:
            try: datetime.date.fromisoformat(p[k])
            except ValueError: raise s.Bad('Enter a valid '+k,k)
    if kind=='events' and not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d',p['time']):raise s.Bad('Enter a valid time','time')
    p['status']=choice(d,'status',{'Open','Closed'}) if 'status' in d else 'Open'
    return p

def post(path,d,me):
    uid=me['id'];now=int(time.time())
    with s.connect() as c:
        if path=='/api/profile':
            first=text(d,'first_name',50);last=text(d,'last_name',50)
            if not s.NAME_OK(first) or not s.NAME_OK(last):raise s.Bad('Names may contain letters, spaces, hyphens')
            university=choice(d,'university',s.UNIVERSITIES)
            email=d.get('email','')
            if not isinstance(email,str) or len(email)>120 or (email and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email)):raise s.Bad('Enter a valid email','email')
            bio=d.get('bio','');interests=d.get('interests','')
            if not isinstance(bio,str) or len(bio)>2000 or not isinstance(interests,str) or len(interests)>200:raise s.Bad('Profile text is too long')
            verified_at=me['email_verified_at'] if email.strip().lower()==(me['email'] or '').strip().lower() else None  # a new address must be confirmed again
            c.execute('UPDATE users SET first_name=?,last_name=?,university=?,email=?,email_verified_at=?,bio=?,interests=? WHERE id=?',(first,last,university,email,verified_at,bio,interests,uid))
            return 200,s.user_json(c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone())
        if path=='/api/community':
            c.execute('UPDATE users SET community=? WHERE id=?',(choice(d,'university',s.UNIVERSITIES),uid));return 200,{'ok':True}
        if path=='/api/password':
            if not isinstance(d.get('current_password'),str) or len(d['current_password'])>128:raise s.Bad('Invalid current password')
            if not hmac.compare_digest(s.hash_pw(d['current_password'],me['pw_salt']),me['pw_hash']):raise s.Bad('Current password is incorrect')
            pw=d.get('password')
            if not isinstance(pw,str) or not 8<=len(pw)<=128:raise s.Bad('Password must have at least 8 characters')
            salt=os.urandom(16);c.execute('UPDATE users SET pw_salt=?,pw_hash=? WHERE id=?',(salt,s.hash_pw(pw,salt),uid))
            c.execute('DELETE FROM sessions WHERE user_id=?',(uid,));return 200,{'ok':True}
        if path=='/api/notifications/read':
            c.execute('UPDATE notifications SET read_at=? WHERE user_id=?',(now,uid));return 200,{'ok':True}
        if path=='/api/messages/read':
            other=number(d,'user_id');c.execute('UPDATE messages SET read_at=? WHERE recipient_id=? AND sender_id=?',(now,uid,other));return 200,{'ok':True}
        if path=='/api/messages':
            other=number(d,'user_id');body=text(d,'text',4000)
            if other==uid or not c.execute('SELECT 1 FROM users WHERE id=?',(other,)).fetchone():raise s.Bad('Recipient not found')
            cur=c.execute('INSERT INTO messages(sender_id,recipient_id,text,created_at) VALUES(?,?,?,?)',(uid,other,body,now))
            notify(c,other,me['first_name']+' sent a message','messages.html?user='+str(uid));return 201,{'id':cur.lastrowid}
        if path=='/api/follow':
            other=number(d,'user_id')
            if other==uid or not c.execute('SELECT 1 FROM users WHERE id=?',(other,)).fetchone():raise s.Bad('User not found')
            if c.execute('SELECT 1 FROM follows WHERE user_id=? AND target_id=?',(uid,other)).fetchone():c.execute('DELETE FROM follows WHERE user_id=? AND target_id=?',(uid,other))
            else:c.execute('INSERT INTO follows VALUES(?,?)',(uid,other))
            return 200,{'ok':True}
        m=re.fullmatch(r'/api/posts/(\d+)/(like|comments|edit|report)',path)
        if m:
            pid=int(m[1]);p=c.execute('SELECT * FROM posts WHERE id=? AND user_id IS NOT NULL',(pid,)).fetchone()
            if not p:raise s.Bad('Post not found',code=404)
            if m[2]=='like':
                if c.execute('SELECT 1 FROM reactions WHERE user_id=? AND post_id=?',(uid,pid)).fetchone():c.execute('DELETE FROM reactions WHERE user_id=? AND post_id=?',(uid,pid))
                else:c.execute('INSERT INTO reactions VALUES(?,?)',(uid,pid))
            elif m[2]=='edit':
                if p['user_id']!=uid:raise s.Bad('Only the author can edit this post',code=403)
                c.execute('UPDATE posts SET text=?,category=? WHERE id=?',(text(d,'text',500),choice(d,'category',s.CATEGORIES_POST),pid))
            elif m[2]=='report':
                if p['user_id']==uid:raise s.Bad('You cannot report your own post')
                reason=choice(d,'reason',REASONS)
                if c.execute('SELECT 1 FROM reports WHERE post_id=? AND user_id=?',(pid,uid)).fetchone():raise s.Bad('You have already reported this post',code=409)
                c.execute('INSERT INTO reports(post_id,user_id,reason,created_at) VALUES(?,?,?,?)',(pid,uid,reason,now))
            else:
                c.execute('INSERT INTO comments(user_id,post_id,text,created_at) VALUES(?,?,?,?)',(uid,pid,text(d,'text',2000),now))
                if p['user_id']!=uid:notify(c,p['user_id'],me['first_name']+' replied to your post','feed.html?post='+str(pid))
            return 200,{'ok':True}
        m=re.fullmatch(r'/api/products/(\d+)/edit',path)
        if m:
            row=c.execute('SELECT image FROM products WHERE id=? AND user_id=?',(int(m[1]),uid)).fetchone()
            if not row:raise s.Bad('Listing not found',code=404)
            image=row['image'] if d.get('keep_image') is True else d.get('image','')
            if not isinstance(image,str) or len(image)>2800000:raise s.Bad('Image must be smaller than 2 MB')
            if image and d.get('keep_image') is not True:
                mm=IMAGE_RE.fullmatch(image)
                if not mm:raise s.Bad('Upload a PNG, JPEG or WebP image')
                try: raw=base64.b64decode(mm[2],validate=True)
                except ValueError:raise s.Bad('Invalid image')
                if len(raw)>2000000 or not (raw.startswith(b'\x89PNG\r\n\x1a\n') or raw.startswith(b'\xff\xd8\xff') or (raw[:4]==b'RIFF' and raw[8:12]==b'WEBP')):raise s.Bad('Invalid image')
            c.execute('UPDATE products SET name=?,price=?,category=?,condition=?,status=?,image=? WHERE id=?',(text(d,'name',80),number(d,'price'),choice(d,'category',s.CATEGORIES_PRODUCT),text(d,'condition',40),choice(d,'status',{'Available','Sold'}),image,int(m[1])))
            return 200,{'ok':True}
        m=re.fullmatch(r'/api/entries/([a-z]+)(?:/(\d+))?',path)
        if m:
            kind=m[1]
            if kind not in KINDS:raise s.Bad('Unknown section',code=404)
            p=payload(kind,d);uni=choice(d,'university',s.UNIVERSITIES)
            if m[2]:
                cur=c.execute('UPDATE entries SET payload=?,university=? WHERE id=? AND user_id=? AND kind=?',(json.dumps(p),uni,int(m[2]),uid,kind))
                if not cur.rowcount:raise s.Bad('Record not found',code=404)
                eid=int(m[2])
            else:
                if kind in ('students','roommates') and c.execute('SELECT 1 FROM entries WHERE user_id=? AND kind=?',(uid,kind)).fetchone():raise s.Bad('You already have a profile here. Edit the existing profile.',code=409)
                eid=c.execute('INSERT INTO entries(kind,user_id,university,payload,created_at) VALUES(?,?,?,?,?)',(kind,uid,uni,json.dumps(p),now)).lastrowid
            return 200,{'id':eid}
        m=re.fullmatch(r'/api/entries/(\d+)/response',path)
        if m:
            eid=int(m[1]);r=c.execute('SELECT * FROM entries WHERE id=?',(eid,)).fetchone()
            if not r:raise s.Bad('Record not found',code=404)
            allowed={'events':{'Interested','Going'},'groups':{'Joined'},'clubs':{'Joined'},'opportunities':{'Applied'},'discounts':{'Saved'}}
            if r['kind'] not in allowed:raise s.Bad('This record does not accept responses')
            status=choice(d,'status',allowed[r['kind']]|{''})
            p=json.loads(r['payload'])
            expires=p.get('deadline') or p.get('expires') or p.get('date')
            if status and (p.get('status')=='Closed' or (expires and expires<datetime.date.today().isoformat())):raise s.Bad('This listing is closed or expired')
            c.execute('DELETE FROM responses WHERE user_id=? AND entry_id=?',(uid,eid))
            if status:
                c.execute('INSERT INTO responses VALUES(?,?,?)',(uid,eid,status))
                if r['user_id']!=uid:notify(c,r['user_id'],me['first_name']+': '+status+' — '+p['name'],{'events':'events','groups':'studymate','clubs':'university','opportunities':'opportunities','discounts':'discounts'}[r['kind']]+'.html')
            return 200,{'ok':True}
        m=re.fullmatch(r'/api/admin/(posts|products)/(\d+)/(remove|dismiss)',path)
        if m:
            if not is_admin(me):raise s.Bad('Moderators only',code=403)
            row=c.execute('SELECT * FROM '+m[1]+' WHERE id=? AND user_id IS NOT NULL',(int(m[2]),)).fetchone()
            if not row:raise s.Bad('Record not found',code=404)
            kind=m[1][:-1];excerpt=(row['text'] if kind=='post' else row['name'])[:200]
            if m[3]=='dismiss':
                if kind!='post' or not c.execute('DELETE FROM reports WHERE post_id=?',(row['id'],)).rowcount:raise s.Bad('This post has no open reports',code=404)
                reason='Reports reviewed, post kept'
            else:
                reason=choice(d,'reason',REASONS)
                c.execute('DELETE FROM '+m[1]+' WHERE id=?',(row['id'],))
                if row['user_id']!=uid:notify(c,row['user_id'],f'A moderator removed your {kind} ({reason}): {excerpt[:60]}','notifications.html')
            c.execute('INSERT INTO moderation_log(admin_id,action,target_kind,target_id,author_id,excerpt,reason,created_at) VALUES(?,?,?,?,?,?,?,?)',
                      (uid,'removed' if m[3]=='remove' else 'kept',kind,row['id'],row['user_id'],excerpt,reason,now))
            return 200,{'ok':True}
    if path=='/api/email/send-code':return send_code(d,me)
    if path=='/api/email/verify':return verify_code(d,me)
    if path=='/api/spaces/watch':return watch_space(d,me)
    return None

def delete(path,me):
    m=re.fullmatch(r'/api/(entries|comments)/(\d+)',path)
    if not m:return None
    with s.connect() as c:
        cur=c.execute('DELETE FROM '+m[1]+' WHERE id=? AND user_id=?',(int(m[2]),me['id']))
    return (200,{'deleted':1}) if cur.rowcount else (404,{'error':'Record not found'})

# ---- R1: email verification by one-time code --------------------------------
CODE_TTL=600;CODE_COOLDOWN=60;SENDS_PER_HOUR=5;MAX_ATTEMPTS=5
EMAIL_RE=re.compile(r'[^@\s]+@[^@\s]+\.[^@\s]+')

def code_hash(uid,code): return hashlib.sha256(f'{uid}:{code}'.encode()).hexdigest()

def send_mail(to,subject,body):
    user=os.environ.get('SMTP_USER');password=os.environ.get('SMTP_PASSWORD')
    if not user or not password:
        if not s.MAIL_DEV:raise s.Bad('Email sending is not configured on this server',code=503)
        print(f'[mail] to {to}: {subject}',file=sys.stderr,flush=True)  # local/demo server: the "email" appears in the console
        if os.environ.get('UNIHUB_MAIL_OUTBOX'):
            with open(os.environ['UNIHUB_MAIL_OUTBOX'],'a',encoding='utf-8') as f:f.write(json.dumps({'to':to,'subject':subject,'body':body})+'\n')
        return
    msg=EmailMessage();msg['Subject']=subject;msg['From']=os.environ.get('SMTP_FROM') or f'UniHub <{user}>';msg['To']=to;msg.set_content(body)
    try:
        with smtplib.SMTP_SSL(os.environ.get('SMTP_HOST','smtp.gmail.com'),int(os.environ.get('SMTP_PORT','465')),timeout=15) as smtp:
            smtp.login(user,password);smtp.send_message(msg)
    except (OSError,smtplib.SMTPException) as e:
        print('[mail] failed:',repr(e),file=sys.stderr,flush=True);raise s.Bad('Could not send the email. Check the address and try again.','email',502)

def send_code(d,me):
    email=d.get('email');uid=me['id'];now=int(time.time())
    if not isinstance(email,str) or len(email.strip())>120 or not EMAIL_RE.fullmatch(email.strip()):raise s.Bad('Enter a valid email','email')
    email=email.strip()
    if me['email_verified_at'] and email.lower()==(me['email'] or '').lower():raise s.Bad('This email is already verified','email')
    with s.connect() as c:
        taken=c.execute('SELECT 1 FROM users WHERE lower(email)=lower(?) AND email_verified_at IS NOT NULL AND id!=?',(email,uid)).fetchone()
        r=c.execute('SELECT * FROM email_codes WHERE user_id=?',(uid,)).fetchone()
    if taken:raise s.Bad('This email is already verified on another account','email',409)
    if r and now-r['sent_at']<CODE_COOLDOWN:raise s.Bad(f"Wait {CODE_COOLDOWN-(now-r['sent_at'])} s before requesting a new code",None,429)
    window,sends=(r['window_start'],r['sends']) if r and now-r['window_start']<3600 else (now,0)
    if sends>=SENDS_PER_HOUR:raise s.Bad('Too many codes requested. Try again in an hour.',None,429)
    code=f'{secrets.randbelow(10**6):06d}'
    # Send first, store after: a failed delivery leaves nothing behind and does not start the cooldown.
    send_mail(email,f'{code} is your UniHub verification code',
              f"Hi {me['first_name']},\n\nYour UniHub verification code is {code}.\nIt expires in 10 minutes.\n\n"
              "If you did not request it, you can ignore this email.\n\nUniHub")
    with s.connect() as c:
        c.execute('DELETE FROM email_codes WHERE user_id=?',(uid,))
        c.execute('INSERT INTO email_codes(user_id,email,code_hash,expires_at,attempts,sent_at,window_start,sends) VALUES(?,?,?,?,0,?,?,?)',
                  (uid,email,code_hash(uid,code),now+CODE_TTL,now,window,sends+1))
    return 200,{'sent':True,'email':email,'expires_in':CODE_TTL}

def verify_code(d,me):
    code=d.get('code');uid=me['id'];now=int(time.time())
    if not isinstance(code,str) or not re.fullmatch(r'\d{6}',code.strip()):raise s.Bad('Enter the 6-digit code','code')
    error=None
    with s.connect() as c:  # errors are raised after the block, so the attempt counter is committed
        r=c.execute('SELECT * FROM email_codes WHERE user_id=?',(uid,)).fetchone()
        if not r or r['expires_at']<now:error=('The code has expired. Request a new one.',400)
        elif r['attempts']>=MAX_ATTEMPTS:error=('Too many wrong attempts. Request a new code.',429)
        elif not hmac.compare_digest(code_hash(uid,code.strip()),r['code_hash']):
            c.execute('UPDATE email_codes SET attempts=attempts+1 WHERE user_id=?',(uid,))
            left=MAX_ATTEMPTS-r['attempts']-1;error=(f'Wrong code. {left} attempts left.' if left else 'Wrong code. Request a new one.',400)
        elif c.execute('SELECT 1 FROM users WHERE lower(email)=lower(?) AND email_verified_at IS NOT NULL AND id!=?',(r['email'],uid)).fetchone():
            error=('This email is already verified on another account',409)
        else:
            c.execute('UPDATE users SET email=?,email_verified_at=? WHERE id=?',(r['email'],now,uid))
            c.execute('DELETE FROM email_codes WHERE user_id=?',(uid,))
            u=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    if error:raise s.Bad(error[0],'code',error[1])
    return 200,s.user_json(u)

# ---- R7: reports, moderation and the statistics panel ------------------------
REASONS={'Spam','Harassment','Inappropriate','Misinformation','Other'}

def is_admin(u): return u is not None and u['role']=='admin'

def grant_admins(c):
    for login in filter(None,(x.strip() for x in os.environ.get('ADMIN_LOGINS','').split(','))):
        c.execute("UPDATE users SET role='admin' WHERE login=?",(login,))

# Calendar day in Kazakhstan time (UTC+5) for an epoch-seconds column; the two databases spell it differently.
def DAY(col): return f"to_char(to_timestamp({col}+18000) AT TIME ZONE 'UTC','YYYY-MM-DD')" if getattr(s,'POSTGRES',False) else f"date({col}+18000,'unixepoch')"
def DAY_NOW(): return time.strftime('%Y-%m-%d',time.gmtime(time.time()+18000))

# Engagement per feed category: likes and comments are pre-aggregated per post so the joins cannot multiply rows.
CATEGORY_SQL='''SELECT p.category, COUNT(*) AS posts, COALESCE(SUM(l.n),0) AS likes, COALESCE(SUM(k.n),0) AS comments
FROM posts p
LEFT JOIN (SELECT post_id, COUNT(*) AS n FROM reactions GROUP BY post_id) l ON l.post_id = p.id
LEFT JOIN (SELECT post_id, COUNT(*) AS n FROM comments GROUP BY post_id) k ON k.post_id = p.id
WHERE p.user_id IS NOT NULL GROUP BY p.category ORDER BY posts DESC, p.category'''
MARKET_SQL='''SELECT category, COUNT(*) AS listings, AVG(price) AS avg_price, SUM(CASE WHEN status = 'Sold' THEN 1 ELSE 0 END) AS sold
FROM products WHERE user_id IS NOT NULL GROUP BY category ORDER BY listings DESC, category'''

def admin(me):
    if not is_admin(me):return 403,{'error':'Moderators only'}
    since=(int(time.time())+18000)//86400*86400-18000-13*86400  # local midnight 13 days ago: a 14-day window
    with s.connect() as c:
        one=lambda q,a=():int(c.execute(q,a).fetchone()[0])
        reports=[]
        for r in c.execute('SELECT post_id,COUNT(*) AS n,MAX(created_at) AS last_at FROM reports GROUP BY post_id ORDER BY n DESC,last_at DESC').fetchall():
            p=c.execute('SELECT p.*,u.first_name,u.last_name FROM posts p JOIN users u ON u.id=p.user_id WHERE p.id=?',(r['post_id'],)).fetchone()
            reasons={x['reason']:int(x['n']) for x in c.execute('SELECT reason,COUNT(*) AS n FROM reports WHERE post_id=? GROUP BY reason ORDER BY n DESC',(r['post_id'],))}
            reports.append({'post_id':p['id'],'text':p['text'],'category':p['category'],'university':p['university'],'author':s.short_name(p['first_name'],p['last_name']),
                            'author_id':p['user_id'],'count':int(r['n']),'last_at':r['last_at'],'reasons':reasons})
        log=[dict(r) for r in c.execute('SELECT m.action,m.target_kind,m.excerpt,m.reason,m.created_at,u.first_name AS admin FROM moderation_log m LEFT JOIN users u ON u.id=m.admin_id ORDER BY m.id DESC LIMIT 30')]
        totals={'users':one('SELECT COUNT(*) FROM users'),'verified':one('SELECT COUNT(*) FROM users WHERE email_verified_at IS NOT NULL'),
                'posts':one('SELECT COUNT(*) FROM posts WHERE user_id IS NOT NULL'),'listings':one('SELECT COUNT(*) FROM products WHERE user_id IS NOT NULL'),
                'comments':one('SELECT COUNT(*) FROM comments'),'likes':one('SELECT COUNT(*) FROM reactions'),'open_reports':len(reports)}
        categories=[{'category':r['category'],'posts':int(r['posts']),'likes':int(r['likes']),'comments':int(r['comments'])} for r in c.execute(CATEGORY_SQL)]
        market=[{'category':r['category'],'listings':int(r['listings']),'avg_price':round(float(r['avg_price'] or 0)),'sold':int(r['sold'])} for r in c.execute(MARKET_SQL)]
        days={'posts':{r['day']:int(r['n']) for r in c.execute(f"SELECT {DAY('sort_key')} AS day,COUNT(*) AS n FROM posts WHERE user_id IS NOT NULL AND sort_key>=? GROUP BY day",(since,))},
              'users':{r['day']:int(r['n']) for r in c.execute(f"SELECT {DAY('created_at')} AS day,COUNT(*) AS n FROM users WHERE created_at>=? GROUP BY day",(since,))}}
    return 200,{'reports':reports,'log':log,'stats':{'totals':totals,'categories':categories,'market':market,'days':days,'today':DAY_NOW()}}


# ---- D3: study-room occupancy sensors (IoT simulation) ----------------------
# A LoRaWAN network server would POST every uplink to /api/iot/readings; report/tools/d3_simulator.py plays
# that role. Students only ever see free / busy / full, never a raw head count (privacy, Part D2).
READING_TTL=30*86400;STALE_AFTER=15*60

def space_status(occupancy,capacity,at,now):
    if at is None or now-at>STALE_AFTER:return 'offline'
    return 'free' if occupancy*2<=capacity else 'busy' if occupancy<capacity else 'full'

def spaces(me):
    now=int(time.time())
    with s.connect() as c:
        watching={r[0] for r in c.execute('SELECT space_id FROM space_watches WHERE user_id=?',(me['id'],))}
        out=[]
        for sp in c.execute('SELECT * FROM spaces ORDER BY building,name').fetchall():
            r=c.execute('SELECT occupancy,created_at FROM space_readings WHERE space_id=? ORDER BY created_at DESC,id DESC LIMIT 1',(sp['id'],)).fetchone()
            status=space_status(r['occupancy'],sp['capacity'],r['created_at'],now) if r else 'offline'
            level=min(4,-(-r['occupancy']*4//sp['capacity'])) if status!='offline' else 0  # filled quarters, rounded up
            out.append({'id':sp['id'],'name':sp['name'],'building':sp['building'],'capacity':sp['capacity'],'status':status,'level':level,
                        'updated_at':r['created_at'] if r else None,'watching':sp['id'] in watching})
    return 200,{'spaces':out,'now':now}

def watch_space(d,me):
    sid=number(d,'space_id');on=d.get('on') is not False
    with s.connect() as c:
        if not c.execute('SELECT 1 FROM spaces WHERE id=?',(sid,)).fetchone():raise s.Bad('Room not found',None,404)
        c.execute('DELETE FROM space_watches WHERE user_id=? AND space_id=?',(me['id'],sid))
        if on:c.execute('INSERT INTO space_watches(user_id,space_id,created_at) VALUES(?,?,?)',(me['id'],sid,int(time.time())))
    return 200,{'watching':on}

def iot_reading(d,token):
    secret=os.environ.get('IOT_TOKEN','')
    if not secret:return 404,{'error':'Not found'}  # off unless a sensor network is configured
    if not isinstance(token,str) or not hmac.compare_digest(token.encode(),secret.encode()):return 401,{'error':'Bad device token'}
    device=d.get('device_id');occ=d.get('occupancy');bat=d.get('battery',100)
    if not isinstance(device,str) or not 0<len(device)<=40:raise s.Bad('Invalid device_id')
    if type(occ) is not int or not 0<=occ<=500 or type(bat) is not int or not 0<=bat<=100:raise s.Bad('Invalid reading')
    now=int(time.time())
    with s.connect() as c:
        sp=c.execute('SELECT * FROM spaces WHERE device_id=?',(device,)).fetchone()
        if not sp:return 403,{'error':'Unknown device'}
        c.execute('INSERT INTO space_readings(space_id,occupancy,battery,created_at) VALUES(?,?,?,?)',(sp['id'],occ,bat,now))
        c.execute('DELETE FROM space_readings WHERE space_id=? AND created_at<?',(sp['id'],now-READING_TTL))
        status=space_status(occ,sp['capacity'],now,now);notified=0
        if status=='free':  # the rule: tell everyone waiting for this room, once
            for w in c.execute('SELECT user_id FROM space_watches WHERE space_id=?',(sp['id'],)).fetchall():
                notify(c,w['user_id'],f"{sp['name']} ({sp['building']}) has free seats now",'studymate.html#rooms');notified+=1
            c.execute('DELETE FROM space_watches WHERE space_id=?',(sp['id'],))
    return 201,{'space':sp['name'],'status':status,'notified':notified}


# ---- log-in rate limit, kept in the database so every server instance shares it ----
LOGIN_WINDOW=300;LOGIN_MAX_FAILS=5

def login_blocked(c,login,ip,now):
    c.execute('DELETE FROM login_failures WHERE at<?',(now-LOGIN_WINDOW,))
    return c.execute('SELECT COUNT(*) FROM login_failures WHERE login=? AND ip=?',(login,ip)).fetchone()[0]>=LOGIN_MAX_FAILS

def login_failed(c,login,ip,now):
    c.execute('INSERT INTO login_failures(login,ip,at) VALUES(?,?,?)',(login,ip,now))

def login_ok(c,login,ip):
    c.execute('DELETE FROM login_failures WHERE login=? AND ip=?',(login,ip))
