"""HTTP integration tests: isolated database, multiple accounts, real server restart."""
import unittest, tempfile, subprocess, sys, os, time, json, urllib.request, urllib.error, http.cookiejar, socket, pathlib, sqlite3
ROOT=pathlib.Path(__file__).resolve().parent
class Client:
 def __init__(self,base):
  self.base=base;self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
 def req(self,method,path,data=None,expected=200,headers=None):
  req=urllib.request.Request(self.base+path,data=None if data is None else json.dumps(data).encode(),method=method,headers={'Content-Type':'application/json',**(headers or {})})
  try:r=self.opener.open(req)
  except urllib.error.HTTPError as e:r=e
  body=r.read();r.close();assert r.status==expected,(path,r.status,body[:300])
  return json.loads(body) if 'application/json' in r.headers.get('Content-Type','') else body
class Integration(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();cls.db=os.path.join(cls.tmp.name,'test.db');cls.outbox=os.path.join(cls.tmp.name,'outbox.jsonl')
  with socket.socket() as sock:sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1]
  cls.base=f'http://127.0.0.1:{cls.port}';cls.start()
 @classmethod
 def start(cls):
  env={k:v for k,v in os.environ.items() if not k.startswith('SMTP_')}  # never send real mail from tests
  cls.proc=subprocess.Popen([sys.executable,str(ROOT/'server.py')],env={**env,'PORT':str(cls.port),'UNIHUB_DB':cls.db,'UNIHUB_MAIL_OUTBOX':cls.outbox},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  for _ in range(100):
   try:urllib.request.urlopen(cls.base+'/login.html');return
   except OSError:time.sleep(.05)
  raise RuntimeError('Server did not start')
 @classmethod
 def tearDownClass(cls):cls.proc.terminate();cls.proc.wait();cls.tmp.cleanup()
 def setUp(self):
  self.a=Client(self.base);self.b=Client(self.base);self.c=Client(self.base)
  suffix=str(time.time_ns())
  def reg(client,name):return client.req('POST','/api/register',dict(first_name=name,last_name='Tester',birth_date='2001-01-01',university='AITU',login=name+suffix,password='test-password-42'),201)
  self.ua=reg(self.a,'Alice');self.ub=reg(self.b,'Boris');self.uc=reg(self.c,'Clara')
 def entry(self,k,extra=None):
  data=dict(university='AITU',name='Community test',description='Test description',date='2099-10-20',time='16:00',venue='Library',category='Study',deadline='2099-10-20',expires='2099-10-20',code='STUDENT',type='Lost',course='CS',year='1st year',subjects='Calculus, Python',format='Online',bio='Looking for partners',budget=100000,district='Yesil',smoking='Non-smoker',pets='No pets',lifestyle='Quiet',sleep='Early bird',subject='Python')
  data.update(extra or {});return self.a.req('POST','/api/entries/'+k,data)['id'],data
 def post(self):return self.a.req('POST','/api/posts',dict(university='AITU',category='Study',text='Test post'),201)['id']
 def test_auth_privacy_and_validation(self):
  Client(self.base).req('GET','/api/data',expected=401)
  self.b.req('POST','/api/login',dict(login=self.ub['login'],password='wrong'),401)
  self.a.req('POST','/api/profile',dict(first_name='<img>',last_name='X',university='AITU'),400)
  for u in self.a.req('GET','/api/data')['users']:self.assertNotIn('email',u);self.assertNotIn('birth_date',u);self.assertNotIn('pw_hash',u)
  self.a.req('POST','/api/posts',dict(university='AITU',category='Study',text='x'),403,{'Origin':'https://other.example'})
 def test_post_like_comment_follow_and_ownership(self):
  pid=self.post();self.b.req('POST',f'/api/posts/{pid}/like',{});self.b.req('POST',f'/api/posts/{pid}/comments',{'text':'Reply'})
  self.b.req('POST','/api/follow',{'user_id':self.ua['id']})
  d=self.b.req('GET','/api/data');p=next(p for p in d['posts'] if p['id']==pid);self.assertEqual((p['likes'],p['comments'],p['followed']),(1,1,True))
  self.b.req('POST',f'/api/posts/{pid}/edit',{'text':'attack','category':'Study'},403);self.b.req('DELETE',f'/api/posts/{pid}',expected=404)
  self.a.req('POST',f'/api/posts/{pid}/edit',{'text':'Updated','category':'Question'})
  self.b.req('POST',f'/api/posts/{pid}/like',{});self.assertEqual(next(p for p in self.b.req('GET','/api/data')['posts'] if p['id']==pid)['likes'],0)
  self.a.req('DELETE',f'/api/posts/{pid}');self.assertFalse(any(c['post_id']==pid for c in self.a.req('GET','/api/data')['comments']))
 def test_entries_all_sections_and_ownership(self):
  for kind in ['students','roommates','events','lost','opportunities','discounts','clubs','groups']:
   eid,d=self.entry(kind);self.assertTrue(any(x['id']==eid for x in self.b.req('GET','/api/data')[kind]))
   self.b.req('POST',f'/api/entries/{kind}/{eid}',d,404);d['status']='Closed';self.a.req('POST',f'/api/entries/{kind}/{eid}',d)
   self.b.req('DELETE',f'/api/entries/{eid}',expected=404);self.a.req('DELETE',f'/api/entries/{eid}')
 def test_responses_notifications_and_members(self):
  for kind,status in [('events','Going'),('clubs','Joined'),('groups','Joined'),('opportunities','Applied'),('discounts','Saved')]:
   eid,_=self.entry(kind);self.b.req('POST',f'/api/entries/{eid}/response',{'status':status})
   x=next(x for x in self.a.req('GET','/api/data')[kind] if x['id']==eid);self.assertEqual(x['participants'][0]['id'],self.ub['id'])
   self.assertEqual(next(x for x in self.b.req('GET','/api/data')[kind] if x['id']==eid)['response'],status)
   self.b.req('POST',f'/api/entries/{eid}/response',{'status':''});self.assertEqual(next(x for x in self.b.req('GET','/api/data')[kind] if x['id']==eid)['response_count'],0)
  self.assertTrue(self.a.req('GET','/api/data')['notifications']);self.a.req('POST','/api/notifications/read',{});self.assertTrue(all(n['read_at'] for n in self.a.req('GET','/api/data')['notifications']))
 def test_closed_expired_and_invalid_entries(self):
  eid,_=self.entry('events',{'date':'2000-01-01'});self.b.req('POST',f'/api/entries/{eid}/response',{'status':'Going'},400)
  eid,_=self.entry('clubs',{'status':'Closed'});self.b.req('POST',f'/api/entries/{eid}/response',{'status':'Joined'},400)
  self.a.req('POST','/api/entries/events',{'name':'x'},400)
  self.a.req('POST','/api/entries/invalid',{},404)
 def test_messages_private_and_read(self):
  mid=self.a.req('POST','/api/messages',{'user_id':self.ub['id'],'text':'Private conversation'},201)['id']
  self.assertTrue(any(m['id']==mid for m in self.b.req('GET','/api/data')['messages']))
  self.assertFalse(any(m['id']==mid for m in self.c.req('GET','/api/data')['messages']))
  self.b.req('POST','/api/messages/read',{'user_id':self.ua['id']});self.assertTrue(next(m for m in self.a.req('GET','/api/data')['messages'] if m['id']==mid)['read_at'])
  self.a.req('POST','/api/messages',{'user_id':self.ua['id'],'text':'self'},400)
 def test_marketplace_photos_and_sold(self):
  d=dict(name='Book',price=100,category='Books',condition='Used',university='AITU');pid=self.a.req('POST','/api/products',d,201)['id']
  d.update(status='Sold',image='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=')
  self.a.req('POST',f'/api/products/{pid}/edit',d);p=next(p for p in self.b.req('GET','/api/data')['products'] if p['id']==pid);self.assertEqual(p['status'],'Sold');self.assertTrue(p['image'])
  self.b.req('POST',f'/api/products/{pid}/edit',d,404);d['image']='javascript:alert(1)';self.a.req('POST',f'/api/products/{pid}/edit',d,400)
  url=p['image'];self.assertTrue(url.startswith(f'/api/products/{pid}/image?v='));self.assertNotIn('base64',json.dumps(self.b.req('GET','/api/data')))
  self.assertTrue(self.b.req('GET',url).startswith(b'\x89PNG'));Client(self.base).req('GET',url,expected=401)
  self.a.req('POST',f'/api/products/{pid}/edit',dict(d,image='',keep_image=True,status='Available'))
  self.assertEqual(next(p for p in self.a.req('GET','/api/data')['products'] if p['id']==pid)['image'],url)
  r=urllib.request.urlopen(urllib.request.Request(self.base+'/app.js',headers={'Accept-Encoding':'gzip'}));self.assertEqual(r.headers['Content-Encoding'],'gzip');r.close()
 def test_profile_password_and_session_revocation(self):
  d=dict(first_name='Alice',last_name='Updated',university='ENU',email='alice@example.test',bio='Hello',interests='Python')
  self.a.req('POST','/api/profile',d);self.a.req('POST','/api/community',{'university':'MNU'});self.assertEqual(self.a.req('GET','/api/me')['community'],'MNU')
  self.a.req('POST','/api/password',{'current_password':'wrong-pass','password':'new-password'},400)
  self.a.req('POST','/api/password',{'current_password':'test-password-42','password':'new-password'})
  self.a.req('GET','/api/me',expected=401);self.a.req('POST','/api/login',{'login':self.ua['login'],'password':'new-password'})
 def test_restart_persists_data(self):
  pid=self.post();eid,_=self.entry('events');self.b.req('POST',f'/api/entries/{eid}/response',{'status':'Going'})
  type(self).proc.terminate();type(self).proc.wait();type(self).start()
  self.assertTrue(any(p['id']==pid for p in self.a.req('GET','/api/data')['posts']));self.assertEqual(next(p for p in self.b.req('GET','/api/data')['events'] if p['id']==eid)['response'],'Going')
 def last_code(self,to):
  mails=[json.loads(l) for l in pathlib.Path(self.outbox).read_text(encoding='utf-8').splitlines()];m=[m for m in mails if m['to']==to][-1]
  return m['subject'].split()[0]
 def wait_cooldown(self,uid):
  with sqlite3.connect(self.db) as c:c.execute('UPDATE email_codes SET sent_at=sent_at-60 WHERE user_id=?',(uid,))
  c.close()
 def test_email_verification_by_code(self):
  mail=f'alice{time.time_ns()}@gmail.com';self.assertFalse(self.a.req('GET','/api/me')['email_verified'])
  self.a.req('POST','/api/email/send-code',{'email':'not-an-email'},400)
  self.assertEqual(self.a.req('POST','/api/email/send-code',{'email':mail})['email'],mail);code=self.last_code(mail);self.assertRegex(code,r'^\d{6}$')
  self.a.req('POST','/api/email/send-code',{'email':mail},429)  # 60 s cooldown between codes
  self.a.req('POST','/api/email/verify',{'code':'1234'},400);wrong=f'{(int(code)+1)%10**6:06d}'
  self.assertIn('4 attempts left',self.a.req('POST','/api/email/verify',{'code':wrong},400)['error'])
  u=self.a.req('POST','/api/email/verify',{'code':code});self.assertTrue(u['email_verified']);self.assertEqual(u['email'],mail)
  self.assertTrue(next(x for x in self.b.req('GET','/api/data')['users'] if x['id']==self.ua['id'])['verified'])
  self.a.req('POST','/api/email/verify',{'code':code},400)  # a code works once
  self.b.req('POST','/api/email/send-code',{'email':mail.upper()},409)  # one verified account per address
  self.a.req('POST','/api/profile',dict(first_name='Alice',last_name='Tester',university='AITU',email='other@example.test'))
  self.assertFalse(self.a.req('GET','/api/me')['email_verified'])  # a changed address loses the badge
  self.b.req('POST','/api/email/send-code',{'email':'boris@example.test'});code=self.last_code('boris@example.test')
  for _ in range(5):self.b.req('POST','/api/email/verify',{'code':f'{(int(code)+1)%10**6:06d}'},400)
  self.b.req('POST','/api/email/verify',{'code':code},429)  # locked after 5 wrong attempts
  self.wait_cooldown(self.ub['id']);self.b.req('POST','/api/email/send-code',{'email':'boris@example.test'})
  self.b.req('POST','/api/email/verify',{'code':self.last_code('boris@example.test')})
 def test_reports_and_moderation(self):
  pid=self.post();self.a.req('POST',f'/api/posts/{pid}/report',{'reason':'Spam'},400)  # not your own post
  self.b.req('POST',f'/api/posts/{pid}/report',{'reason':'Nonsense'},400);self.b.req('POST',f'/api/posts/{pid}/report',{'reason':'Spam'})
  self.b.req('POST',f'/api/posts/{pid}/report',{'reason':'Spam'},409)
  self.b.req('GET','/api/admin',expected=403);self.b.req('POST',f'/api/admin/posts/{pid}/remove',{'reason':'Spam'},403)
  Client(self.base).req('GET','/api/admin',expected=401)
  with sqlite3.connect(self.db) as c:c.execute("UPDATE users SET role='admin' WHERE id=?",(self.uc['id'],))
  c.close();self.assertEqual(self.c.req('GET','/api/me')['role'],'admin')
  d=self.c.req('GET','/api/admin');r=next(r for r in d['reports'] if r['post_id']==pid);self.assertEqual((r['count'],r['reasons']),(1,{'Spam':1}))
  self.assertGreaterEqual(d['stats']['totals']['posts'],1);self.assertTrue(any(x['category']=='Study' for x in d['stats']['categories']))
  self.assertGreaterEqual(d['stats']['days']['posts'].get(d['stats']['today'],0),1)
  self.c.req('POST',f'/api/admin/posts/{pid}/dismiss',{});self.assertFalse(any(r['post_id']==pid for r in self.c.req('GET','/api/admin')['reports']))
  self.c.req('POST',f'/api/admin/posts/{pid}/dismiss',{},404);self.c.req('POST',f'/api/admin/posts/{pid}/remove',{'reason':'Wrong'},400)
  self.c.req('POST',f'/api/admin/posts/{pid}/remove',{'reason':'Spam'});self.assertFalse(any(p['id']==pid for p in self.a.req('GET','/api/data')['posts']))
  self.assertIn('moderator removed your post',self.a.req('GET','/api/data')['notifications'][0]['text'])
  pr=self.a.req('POST','/api/products',dict(name='Fake',price=1,category='Other',condition='New',university='AITU'),201)['id']
  self.c.req('POST',f'/api/admin/products/{pr}/remove',{'reason':'Spam'});self.assertFalse(any(p['id']==pr for p in self.a.req('GET','/api/data')['products']))
  self.assertEqual([x['action'] for x in self.c.req('GET','/api/admin')['log'][:3]],['removed','removed','kept'])
 def test_routes_and_database_integrity(self):
  for f in (ROOT/'site').glob('*.html'):self.assertIn(b'<!doctype html>',self.a.req('GET','/'+f.name))
  with sqlite3.connect(self.db) as c:self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok');self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
  c.close()
if __name__=='__main__':unittest.main(verbosity=2)
