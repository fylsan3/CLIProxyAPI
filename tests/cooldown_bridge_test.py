"""Deferred local-only receipt and maintenance regression tests."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from header_policy import cooldown_receipt_headers, response_headers
from maintenance import MaintenanceGate

class CooldownBridge(unittest.TestCase):
 def test_private_receipt_and_body_independence(self):
  h={'X-Offline-Cooldown-Bridge':['1'],'X-Offline-Retry-At':['2026-11-26T00:00:30Z'],'X-Offline-Credential-Scope':['true'],'X-Offline-Transient-Rate-Limit':['false'],'Retry-After':['30']}
  self.assertEqual(len(cooldown_receipt_headers(h)),4)
  self.assertEqual(response_headers(h),{'Retry-After':['30']})
  h['X-Offline-Retry-At']=['bad\r\nInjected: value']
  self.assertEqual(cooldown_receipt_headers(h),{})
 def test_busy_a_does_not_block_b(self):
  gate=MaintenanceGate()
  with gate.request('A'):
   with self.assertRaisesRegex(ValueError,'account_busy'):
    with gate.maintenance('A'):pass
   with gate.maintenance('B'):pass
  with gate.maintenance('A'):
   with self.assertRaisesRegex(ValueError,'account_maintenance'):
    with gate.request('A'):pass
   with gate.request('B'):pass
  with gate.request('A'):pass

if __name__=='__main__':unittest.main()
