from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.config import AppSettings
from src.database import DataStore, create_database, create_session_factory


@pytest.fixture
def market_frame() -> pd.DataFrame:
    rows = 360
    index = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("5min"), periods=rows, freq="5min")
    base = np.linspace(80, 120, rows) + np.sin(np.arange(rows) / 8)
    open_ = base - 0.15
    close = base + 0.15
    return pd.DataFrame(
        {
            "open": open_,
            "high": base + 0.8,
            "low": base - 0.8,
            "close": close,
            "volume": np.full(rows, 100_000.0),
        },
        index=index,
    )


@pytest.fixture
def store() -> DataStore:
    settings = AppSettings(database_url="sqlite:///:memory:")
    engine = create_database(settings.database_url)
    result = DataStore(create_session_factory(engine), settings)
    result.seed_defaults()
    return result
