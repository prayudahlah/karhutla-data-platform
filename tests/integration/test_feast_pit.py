from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("pandas")
pytest.importorskip("pyarrow")
pytest.importorskip("feast")

import pandas as pd  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.dataset as ds  # noqa: E402
from feast import (  # noqa: E402
    Entity,
    FeatureService,
    FeatureView,
    Field,
    FileSource,
    ValueType,
)
from feast.data_format import ParquetFormat  # noqa: E402
from feast.types import Float64  # noqa: E402


def test_feast_historical_join_is_point_in_time(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    data = tmp_path / "data"
    repo.mkdir()
    data.mkdir()

    frame = pd.DataFrame(
        {
            "cell_id": ["A", "A"],
            "event_timestamp": [datetime(2026, 9, 1), datetime(2026, 9, 2)],
            "created_timestamp": [datetime(2026, 10, 1), datetime(2026, 10, 1)],
            "date": [datetime(2026, 9, 1).date(), datetime(2026, 9, 2).date()],
            "value": [1.0, 2.0],
        }
    )
    table = pa.Table.from_pandas(frame, preserve_index=False)
    table = table.set_column(
        table.schema.get_field_index("date"),
        "date",
        table["date"].cast(pa.date32()),
    )
    ds.write_dataset(
        table,
        data,
        format="parquet",
        partitioning=ds.partitioning(pa.schema([("date", pa.date32())]), flavor="hive"),
        basename_template="data_{i}.parquet",
    )

    (repo / "feature_store.yaml").write_text(
        "\n".join(
            [
                "project: pit_test",
                "registry: registry.db",
                "provider: local",
                "offline_store:",
                "  type: duckdb",
                "online_store:",
                "  path: online.db",
                "entity_key_serialization_version: 3",
                "",
            ]
        ),
        encoding="utf-8",
    )

    from feast import FeatureStore

    cell = Entity(name="cell", join_keys=["cell_id"], value_type=ValueType.STRING)
    source = FileSource(
        name="cell_source",
        path=data.as_posix(),
        file_format=ParquetFormat(),
        timestamp_field="event_timestamp",
        created_timestamp_column="created_timestamp",
    )
    view = FeatureView(
        name="cell_features",
        entities=[cell],
        ttl=timedelta(days=3650),
        schema=[Field(name="value", dtype=Float64)],
        source=source,
    )
    service = FeatureService(name="pit_service", features=[view[["value"]]])

    store = FeatureStore(repo_path=str(repo))
    store.apply([cell, source, view, service])

    entity_df = pd.DataFrame(
        {
            "cell_id": ["A", "A"],
            "event_timestamp": [datetime(2026, 9, 1), datetime(2026, 9, 4)],
        }
    )
    result = store.get_historical_features(
        entity_df=entity_df,
        features=store.get_feature_service("pit_service"),
    ).to_df()
    result = result.sort_values("event_timestamp").reset_index(drop=True)

    assert result["value"].tolist() == [1.0, 2.0]
