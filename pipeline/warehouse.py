"""The warehouse boundary: making silver Parquet queryable, so dbt can transform it.

**The lakehouse decision, made concrete** (DECISIONS.md D4). Neither implementation *copies* the data.
DuckDB reads the Parquet directly through views; BigQuery registers it as **BigLake external tables**
over the same objects in GCS. One copy of the bytes, in an open format, queryable by whatever engine we
point at it. The only thing that becomes a native warehouse table is the small serving mart dbt builds
at the end.

That is what makes "lakehouse" a design rather than a word: bulk data stays on cheap object storage in
an open format, and the warehouse supplies the query engine and the modelling layer.

**Why Hive partitioning matters here.** Both silver prefixes are written as ``.../key=value/...``
(sales by ``transaction_date``, sports by ``ingest_date``). Both engines read that natively and turn it
into a real, prunable partition column, so a query for one day opens one directory rather than scanning
the lake. Cheapest performance decision available, and it costs nothing but a naming convention.

NOTE ON FORM: pseudocode, except the external-table DDL, which is the part worth reviewing.
"""

from typing import Any, Dict, List, Optional

# The two raw tables dbt sources from. Named `raw_` because from dbt's point of view this IS the raw
# layer: untransformed, exactly as ingestion left it.
TABLE_RAW_SALES = "raw_sales"
TABLE_RAW_SPORTS_EVENTS = "raw_sports_events"


class WarehouseError(RuntimeError):
    """The warehouse cannot be prepared or queried."""


class DuckDBWarehouse:
    """DuckDB standing in for BigQuery, so the pipeline runs with no cloud account.

    Honest about what this does and does not prove (D15): the dbt models and the SQL are the same, and
    dbt's adapters absorb most dialect difference — but DuckDB is not BigQuery, and SQL that passes here
    can still fail there.

    PSEUDOCODE for register_silver()

        for (table, prefix) in [(raw_sales, "silver/sales"), (raw_sports_events, "silver/sports_events")]:
            CREATE OR REPLACE VIEW <table> AS
                SELECT * FROM read_parquet('<data_dir>/<prefix>/**/*.parquet',
                                           hive_partitioning := true,
                                           union_by_name := true)
            # VIEW, not table: re-reads the Parquet on every query, so a re-run of ingestion is
            #   immediately visible and the warehouse never holds a second copy. This is the local
            #   equivalent of a BigLake external table, and keeping them equivalent is the point.
            # union_by_name tolerates a column added to newer files — older files get NULL rather than
            #   the whole read failing. Schema evolution should degrade, not break.
            # the path is INLINED because DuckDB will not bind a parameter inside CREATE VIEW, so
            #   quotes are escaped: a path is still external data.

            on failure (usually: no files yet) -> log WARNING, count 0, CONTINUE
            # an empty view keeps dbt able to parse and build; a hard failure would block the whole
            # project on one missing partition
    """


class BigQueryWarehouse:
    """BigQuery, with silver exposed as BigLake external tables over GCS.

    External rather than loaded, deliberately: the lake keeps one copy of the bytes in an open format,
    we pay GCS rather than BigQuery storage prices for the bulk, and Spark or Trino could read the same
    files tomorrow without an export. The serving mart is the only native table, because it is small
    and queried constantly (D4).

    The client is imported lazily and injectable, so importing this module needs no GCP credentials.

    ``ensure_dataset()`` pins the dataset to ``settings.gcp_location`` — europe-west2 by default. UK
    customer data staying in-region is a data-residency decision, and it MUST be set at creation
    because it cannot be changed afterwards.
    """

    # The DDL, which is the part worth reviewing rather than paraphrasing:
    EXTERNAL_TABLE_DDL = """
        CREATE OR REPLACE EXTERNAL TABLE `{project}.{dataset}.{table}`
        WITH PARTITION COLUMNS
        OPTIONS (
            format = 'PARQUET',
            uris = ['gs://{bucket}/{prefix}/*.parquet'],
            hive_partitioning_mode = 'AUTO',
            hive_partitioning_source_uri_prefix = 'gs://{bucket}/{prefix}'
        )
    """
    # hive_partitioning_mode = AUTO makes BigQuery infer the partition column AND its type from the
    # key=value path, giving a genuinely prunable column rather than a string somebody has to remember
    # to cast.


def build_warehouse(settings: Any):
    """Pick a warehouse from configuration. The ONE place the choice is made.

    PSEUDOCODE:  BigQueryWarehouse(project, dataset, bucket, location) if settings.is_gcp
                 else DuckDBWarehouse(<data_dir>/warehouse.duckdb)
                 raise WarehouseError if TARGET=gcp without GCP_PROJECT / BUCKET_LAKE
    """
    raise NotImplementedError("pseudocode")
