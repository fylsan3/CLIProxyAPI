"""Reject weakened runtime policy and mismatched backup policy before use."""
import copy,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import network_control as network
import portable_backup as backup

class RuntimeSecurityTests(unittest.TestCase):
    def setUp(self):
        self.control=network.Control.__new__(network.Control)
        self.control.seccomp=json.loads((network.ROOT/'security/seccomp.json').read_text())
        self.card=dict(container='fake',image='image',network='private',volume='state',backup='backup',network_config='network')
        self.info={'Image':'image','HostConfig':{'SecurityOpt':['no-new-privileges','seccomp='+json.dumps(self.control.seccomp)],
            'CapAdd':['CAP_'+v for v in ('NET_ADMIN','SETUID','SETGID','SETPCAP','CHOWN','DAC_OVERRIDE','KILL')],
            'CapDrop':['ALL'],'NetworkMode':'private','Privileged':False,'ReadonlyRootfs':True},
            'NetworkSettings':{'Networks':{'private':{}}},'Mounts':[
                {'Destination':'/'+target,'Name':name,'RW':rw} for target,name,rw in
                [('state','state',True),('backup','backup',True),('network-config','network',False)]]}
    def check(self):
        with patch.object(network,'docker',return_value=json.dumps([self.info])):
            return self.control.inspect(self.card)
    def test_expected_policy_accepted(self):self.check()
    def test_unconfined_or_missing_policy_rejected(self):
        for option in ('seccomp=unconfined',None):
            self.info['HostConfig']['SecurityOpt']=['no-new-privileges']+([option] if option else [])
            with self.subTest(option=option),self.assertRaises(ValueError):self.check()
    def test_altered_syscall_policy_rejected(self):
        changed=copy.deepcopy(self.control.seccomp);changed['defaultAction']='SCMP_ACT_ALLOW'
        self.info['HostConfig']['SecurityOpt'][1]='seccomp='+json.dumps(changed)
        with self.assertRaises(ValueError):self.check()
    def test_extra_privilege_rejected(self):
        self.info['HostConfig']['CapAdd'].append('CAP_SYS_ADMIN')
        with self.assertRaises(ValueError):self.check()
    def test_backup_from_different_policy_rejected_before_volume_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);root.chmod(0o700)
            card=dict(self.card,owner='A',security_policy_sha256='current')
            backup.write_json(root/'A.json',card)
            backup.write_json(root/'latest.json',{'spec':{'card':dict(card,security_policy_sha256='old')}})
            control=SimpleNamespace(image='image',card=lambda owner:root/'A.json')
            instance=backup.Packages.__new__(backup.Packages)
            instance.broker=SimpleNamespace(protection=SimpleNamespace(control=control));instance.target=lambda _:root
            with patch.object(backup,'require_original_stopped'),patch.object(backup,'docker') as command:
                with self.assertRaisesRegex(ValueError,'backup_card_changed'):instance.prepare_restore('A')
                command.assert_not_called()

if __name__=='__main__':unittest.main()
