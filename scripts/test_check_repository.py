"""Offline tests: python -m unittest discover -s scripts -p 'test_*.py'."""
import tempfile
import unittest
from pathlib import Path

from check_repository import check, forbidden


class RepositoryChecks(unittest.TestCase):
    def test_private_and_generated_paths(self):
        for name in ['.env', 'apps/web/.env.local', 'private/results.json',
                     'apps/web/node_modules/x.js', 'apps/web/next-env.d.ts', 'db.dump']:
            with self.subTest(name=name):
                self.assertTrue(forbidden(name))
        for name in ['.env.example', 'apps/api/migrations/001_test.sql', 'docs/assets/overview.svg']:
            self.assertFalse(forbidden(name))

    def test_links_and_template(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'README.md').write_text('[Guide](guide.md)\n[External](https://example.org)\n', encoding='utf-8')
            (root / 'guide.md').write_text('# Guide\n', encoding='utf-8')
            (root / '.env.example').write_text('FOOD_API_KEY=\n', encoding='utf-8')
            names = ['README.md', 'guide.md', '.env.example']
            self.assertEqual(check(root, names), [])
            self.assertTrue(check(root, ['README.md']))  # Existing but not publishable.
            (root / '.env.example').write_text('FOOD_API_KEY=not-a-real-key\n', encoding='utf-8')
            self.assertTrue(check(root, names))

    def test_sensitive_patterns_are_redacted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token = 'ghp_' + 'a' * 36
            (root / 'sample.txt').write_text(token + '\n' + 'C:' + '/Users/' + 'example/private', encoding='utf-8')
            errors = check(root, ['sample.txt'])
            self.assertEqual(len(errors), 2)
            self.assertNotIn(token, str(errors))

    def test_svg_and_escaping_link(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'image.svg').write_text('<broken', encoding='utf-8')
            (root / 'README.md').write_text('[Outside](../outside.md)\n', encoding='utf-8')
            self.assertEqual(len(check(root, ['image.svg', 'README.md'])), 2)


if __name__ == '__main__':
    unittest.main()