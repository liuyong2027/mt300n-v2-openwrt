import os
import shutil
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == 'posix' and shutil.which('nc'), 'requires POSIX shell and nc')
class MemoryRecoveryTests(unittest.TestCase):
    def test_bounded_recovery_protocol_and_owner_defaults(self):
        import memory_checks
        source=Path(__file__).resolve().parents[1]/'package/luci-app-mango-proxy/root'
        reports=memory_checks.guard_cases(source, ['sh'])+memory_checks.protocol_cases(source, ['sh'])+memory_checks.dns_cases(source, ['sh'])
        self.assertEqual(len(reports), 42)


if __name__ == '__main__': unittest.main()
