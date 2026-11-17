import unittest
from check_branding import has_legacy_branding


class BrandingTests(unittest.TestCase):
    def test_product_names_and_domains_are_rejected(self):
        for value in ("SoC-Mind", "SOCMIND", "socmind product", "socmind.example", "socmind_arbitrary", "SOCM", "socm.example.com", "SOC-Mind-main"):
            self.assertTrue(has_legacy_branding(value), value)

    def test_known_container_identifier_is_allowed(self):
        self.assertFalse(has_legacy_branding("container_name: socmind_pipeline"))

    def test_compatibility_contracts_remain_allowed(self):
        for value in ("SOC_MIND_MONGO_URL", "soc_mind_platform", "soc_mind_tenant_demo",
                      "X-SOC-Mind-Signature", "soc_mind_token", "soc_mind_kb",
                      "soc-mind-jira-submit", '"soc-mind"'):
            self.assertFalse(has_legacy_branding(value), value)

    def test_unrelated_soc_words_are_not_rejected(self):
        self.assertFalse(has_legacy_branding("SOC metrics and SOC monitoring"))
