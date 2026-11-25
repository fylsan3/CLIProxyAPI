import importlib.util,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import host_runtime
spec=importlib.util.spec_from_file_location('linux_deploy',ROOT/'linux/deploy.py');deploy=importlib.util.module_from_spec(spec);spec.loader.exec_module(deploy)
class HostTests(unittest.TestCase):
 def test_local_engine_selection(self):
  with patch.dict(os.environ,{},clear=True),patch.object(host_runtime.sys,'platform','linux'),patch.object(host_runtime.shutil,'which',return_value='/usr/bin/docker'):
   self.assertEqual(host_runtime.docker_cli(),['/usr/bin/docker','--host','unix:///var/run/docker.sock'])
   os.environ['CPA_DOCKER_HOST']='unix:///run/user/123/docker.sock'
   self.assertEqual(str(host_runtime.docker_socket()),'/run/user/123/docker.sock')
   os.environ['CPA_DOCKER_HOST']='tcp://example.invalid:2375'
   with self.assertRaisesRegex(ValueError,'local_unix'):host_runtime.docker_cli()
 def test_units_are_rendered_without_install(self):
  with tempfile.TemporaryDirectory() as d:
   out=Path(d)/'package';deploy.render(Path('/opt/cpa-test'),out,Path('/etc/cpa/network.json'))
   central=(out/'cpa-central.service').read_text();broker=(out/'cpa-account-broker.service').read_text()
   self.assertIn('Wants=cpa-account-broker.service',central);self.assertIn('StartLimitIntervalSec=0',central);self.assertIn('Wants=docker.service',broker);self.assertIn('User=cpa-central',central);self.assertIn('SupplementaryGroups=cpa-control\n',central)
   self.assertNotIn('SupplementaryGroups=docker',central);self.assertIn('network_guard.py --',central)
   self.assertIn('--control-group cpa-control',broker);self.assertIn('RuntimeDirectoryMode=0750',broker)
   self.assertEqual((out/'install.py').read_bytes(),(ROOT/'linux/install.py').read_bytes())
   with self.assertRaises(FileExistsError):deploy.render(Path('/opt/cpa-test'),out,Path('/etc/cpa/network.json'))
   with self.assertRaises(ValueError):deploy.render(Path('/opt/x\nmalformed'),Path(d)/'bad',Path('/etc/cpa/network.json'))
if __name__=='__main__':unittest.main(verbosity=2)
