"""Read-only checks of Git-visible working-tree files, not Git history or staged blobs."""
import fnmatch
import re
import subprocess
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_PARTS = {
    'private', 'data', 'uploads', 'backups', 'tmp', 'node_modules', '.venv',
    '.next', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache',
    'coverage', 'playwright-report', 'test-results', '.idea', '.vscode',
}
BLOCKED_NAMES = ('*.log', '*.pid', '*.tmp', '*.bak', '*.swp', '*.pyc', '*.pyo',
                 '*.tsbuildinfo', '*.pdf', '*.hwp', '*.hwpx', '*.pem', '*.key',
                 '*.dump', '*.sqlite*', '*.db', '*.zip', '*.p12', '*.pfx', '*.p8',
                 'credentials*.json', 'service-account*.json', '.coverage*',
                 'next-env.d.ts', '.DS_Store', 'Thumbs.db')
PATTERNS = {
    'personal absolute path': re.compile(r'[A-Za-z]:[\\/]+Users[\\/]+[^\s<>]+|/(?:Users|home)/[\w.-]+/'),
    'private key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'access token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[A-Z0-9]{16})\b'),
}


def forbidden(name):
    path = PurePosixPath(name)
    return (any(part in BLOCKED_PARTS for part in path.parts)
            or (path.name.startswith('.env') and path.name != '.env.example')
            or any(fnmatch.fnmatchcase(path.name, pattern) for pattern in BLOCKED_NAMES))


def visible_files(root):
    raw = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=root)
    return sorted({name.decode('utf-8') for name in raw.split(b'\0') if name})


def check(root, names):
    errors = []
    visible = set(names)
    for name in names:
        file = root / name
        if forbidden(name):
            errors.append((name, 'excluded path is Git-visible'))
            continue  # Never inspect or echo confidential contents.
        if file.is_symlink():
            errors.append((name, 'symlink requires manual review'))
            continue
        if not file.is_file():
            errors.append((name, 'tracked file missing; resolve deletion before publication'))
            continue
        if file.stat().st_size > 5 * 1024 * 1024:
            errors.append((name, 'file exceeds 5 MiB review limit'))
            continue
        if file.suffix in {'.woff2', '.png', '.jpg', '.jpeg', '.webp'}:
            continue  # Binary rights/privacy require manual review.
        try:
            text = file.read_text(encoding='utf-8-sig')
        except UnicodeDecodeError:
            errors.append((name, 'unexpected binary or non-UTF-8 file'))
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                errors.append((name, label + ' detected (content withheld)'))
        if file.name == '.env.example':
            for line in text.splitlines():
                key, sep, value = line.partition('=')
                if sep and key.strip() in {'POSTGRES_PASSWORD', 'DATABASE_URL', 'FOOD_API_KEY', 'AI_GATEWAY_API_KEY'} and value.strip():
                    errors.append((name, 'credential template must have empty values'))
        if file.suffix == '.md':
            # Inline Markdown links only; fenced examples and fragment anchors are not checked.
            prose = re.sub(r'^```[^\n]*\n.*?^```\s*$', '', text, flags=re.M | re.S)
            for href in re.findall(r'\]\(([^\s)]+)(?:\s+"[^"]*")?\)', prose):
                link = urlsplit(href.strip('<>'))
                if link.scheme or link.netloc or not link.path:
                    continue
                target = (file.parent / unquote(link.path)).resolve()
                try:
                    relative = target.relative_to(root.resolve()).as_posix()
                except ValueError:
                    errors.append((name, 'local link escapes repository'))
                    continue
                if relative not in visible:
                    errors.append((name, 'local link target is not a publishable file: ' + relative))
        if file.suffix == '.svg':
            try:
                svg = ElementTree.fromstring(text)
                if svg.tag != '{http://www.w3.org/2000/svg}svg':
                    raise ValueError()
            except (ElementTree.ParseError, ValueError):
                errors.append((name, 'invalid SVG document'))
    return errors


def main():
    names = visible_files(ROOT)
    errors = check(ROOT, names)
    for name, message in errors:
        print(f'FAIL: {name}: {message}')
    if errors:
        return 1
    print(f'PASS: {len(names)} Git-visible paths checked; links and text patterns checked.')
    print('Not a full secret/license/privacy audit; binary files and Git history need manual review.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())