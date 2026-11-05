from .config import load_config
from .db import Store

if __name__=='__main__':
    Store(load_config().database_url).migrate()
    print('Database migrations applied')