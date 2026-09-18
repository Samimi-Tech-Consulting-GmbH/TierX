import unittest

from generate_license_artifacts import ROOT, npm_components, python_components


class LicenseInventoryTests(unittest.TestCase):
    def test_shared_runtime_dependency_is_included(self):
        items = python_components(ROOT / "kb_shared/pyproject.toml")
        item = next(value for value in items if value["name"] == "markdown-it-py")
        self.assertEqual(item["version"], "3.0.0")
        self.assertEqual(item["licenses"], [{"license": {"id": "MIT"}}])

    def test_scoped_npm_purl_retains_namespace_separator(self):
        items = npm_components(ROOT / "integrations/jira-forge/package-lock.json")
        scoped = [item for item in items if item["name"].startswith("@")]
        self.assertTrue(scoped)
        for item in scoped:
            self.assertTrue(item["purl"].startswith("pkg:npm/%40"))
            self.assertNotIn("%2F", item["purl"])

    def test_constraints_are_not_reported_as_resolved_versions(self):
        items = python_components(ROOT / "pipeline/requirements.txt")
        for item in items:
            if "version" in item:
                self.assertNotRegex(item["version"], r"[<>=~!,]")

    def test_npm_installations_have_distinct_identity(self):
        items = npm_components(ROOT / "integrations/jira-forge/package-lock.json")
        self.assertEqual(len(items), len({item["bom-ref"] for item in items}))


if __name__ == "__main__":
    unittest.main()
