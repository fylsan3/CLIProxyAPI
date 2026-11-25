"""Create short-lived certificates exclusively for the closed HTTPS test images."""
import os,shutil,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def prepare():
 cert=ROOT/'tls-fixture/server.crt';key=ROOT/'tls-fixture/server.key';ca=ROOT/'tls-test/test-ca.crt'
 if all(p.exists() for p in (cert,key,ca)):
  valid=subprocess.run(['openssl','x509','-checkend','172800','-noout','-in',str(cert)],capture_output=True).returncode==0
  trusted=subprocess.run(['openssl','verify','-CAfile',str(ca),str(cert)],capture_output=True).returncode==0
  if valid and trusted:return
 with tempfile.TemporaryDirectory(prefix='cpa-fixture-ca-') as folder:
  p=Path(folder);p.chmod(0o700)
  def command(*args):subprocess.run(['openssl',*args],cwd=p,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  command('req','-x509','-newkey','rsa:2048','-nodes','-keyout','ca.key','-out','ca.crt','-days','30','-subj','/CN=CPA closed test only')
  command('req','-newkey','rsa:2048','-nodes','-keyout','server.key','-out','server.csr','-subj','/CN=CPA closed HTTPS fixture')
  (p/'extensions').write_text('subjectAltName=DNS:claude.ai,DNS:platform.claude.com,DNS:api.anthropic.com,DNS:ipwho.is,DNS:api.ipify.org,DNS:www.cloudflare.com\nextendedKeyUsage=serverAuth\nbasicConstraints=CA:FALSE\n')
  command('x509','-req','-in','server.csr','-CA','ca.crt','-CAkey','ca.key','-CAcreateserial','-out','server.crt','-days','7','-extfile','extensions')
  for source,target in [('server.crt',cert),('server.key',key),('ca.crt',ca)]:
   temporary=target.with_suffix(target.suffix+'.pending');shutil.copyfile(p/source,temporary);temporary.chmod(0o600 if source=='server.key' else 0o644);temporary.replace(target)
 # The CA signing key was temporary and is never installed in an image.

if __name__=='__main__':prepare();print('Closed-test certificate is ready; no system trust store changed')
