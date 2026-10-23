from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlparse

HUMO_PEER_ID = 856254490


@dataclass(frozen=True)
class BridgeSettings:
    enabled: bool = False
    owner_id: int = 0
    url: str = ''
    token: str = field(default='', repr=False)
    database: Path = Path('data/finance_bridge.sqlite3')
    backfill_days: int = 3

    @classmethod
    def from_env(cls):
        return cls(
            enabled=os.getenv('FINANCE_BRIDGE_ENABLED', 'false').lower() == 'true',
            owner_id=int(os.getenv('FINANCE_OWNER_TG_ID', '0') or '0'),
            url=os.getenv('FINANCE_COLLECTOR_URL', ''),
            token=os.getenv('FINANCE_COLLECTOR_TOKEN', ''),
            database=Path(os.getenv('FINANCE_BRIDGE_DATABASE') or str(Path(os.getenv('DATA_DIR', 'data')) / 'finance_bridge.sqlite3')),
            backfill_days=int(os.getenv('FINANCE_BACKFILL_DAYS', '3')),
        )

    def validate(self):
        parsed = urlparse(self.url)
        if (self.owner_id <= 0 or len(self.token) < 24 or not 1 <= self.backfill_days <= 30
                or parsed.scheme not in {'http', 'https'} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path != '/v1/notifications'):
            raise ValueError('Invalid finance bridge configuration')
