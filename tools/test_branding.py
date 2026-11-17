import unittest
from check_branding import missing_identifiers

class BrandingTests(unittest.TestCase):
    def test_canonical_identifiers_are_required(self):
        self.assertEqual(missing_identifiers('db="tierx_platform"', ['db="tierx_platform"']), [])
        self.assertEqual(missing_identifiers('db="other"', ['db="tierx_platform"']), ['db="tierx_platform"'])
