import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Config:
    database_url: str = field(repr=False)
    food_api_key: str = field(default='', repr=False)
    ai_gateway_api_key: str = field(default='', repr=False)
    model: str = 'claude-sonnet'
    web_origin: str = 'http://localhost:3000'
    cookie_secure: bool = False


def load_config():
    values = {}
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            key, sep, value = line.partition('=')
            if not sep:
                raise ValueError('Invalid configuration line')
            values[key.strip()] = value.strip().strip('"\'')
    values.update(os.environ)
    if not values.get('DATABASE_URL'):
        raise ValueError('DATABASE_URL required; see .env.example')
    return Config(database_url=values['DATABASE_URL'], food_api_key=values.get('FOOD_API_KEY',''),
                  ai_gateway_api_key=values.get('AI_GATEWAY_API_KEY',''),
                  model=values.get('AI_GATEWAY_MODEL','claude-sonnet'),
                  web_origin=values.get('WEB_ORIGIN','http://localhost:3000'),
                  cookie_secure=values.get('COOKIE_SECURE','false').lower() == 'true')