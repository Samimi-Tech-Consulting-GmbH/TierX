import unittest
from check_branding import has_legacy_branding


class BrandingTests(unittest.TestCase):
    def test_product_names_and_domains_are_rejected(self):
        for value in ("SoC-Mind", "SOCMIND", "socmind product", "socmind.example", "socmind_arbitrary"):
            self.assertTrue(has_legacy_branding(value), value)

    def test_known_container_identifier_is_allowed(self):
        self.assertFalse(has_legacy_branding("container_name: socmind_pipeline"))
