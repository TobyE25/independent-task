"""The cloud boundary: where bytes live. Nothing else knows laptop from GCS.

Storage location is the only genuinely cloud-specific concern in the ingestion path, so confining it
to one small interface means the pipeline runs end to end with no cloud account — and the production
path is a config value away (DECISIONS.md D15).

The interface is deliberately tiny: four methods a filesystem and an object store can both honour
cheaply. Anything richer (renames, appends, directory semantics) would leak a filesystem assumption
into code that must run against GCS.

NOTE ON FORM: pseudocode.
"""

from typing import Any, Dict, Iterable, List, Optional

try:
    from typing import Protocol
except ImportError:  # Python 3.7 and earlier
    Protocol = object


class Storage(Protocol):
    """The whole storage contract. Four methods, both backends honour all of them."""

    def write_bytes(self, path: str, data: bytes) -> str:
        """Write ``data`` at ``path``, returning a URI for logging and lineage."""

    def read_bytes(self, path: str) -> bytes: ...

    def exists(self, path: str) -> bool: ...

    def list_paths(self, prefix: str) -> List[str]: ...


class LocalStorage:
    """Filesystem-backed, rooted at a directory. Used for local runs and tests.

    Mimics object-store semantics closely enough that code behaves the same on GCS: flat string paths,
    parents created on demand, writes replace rather than append.

    PSEUDOCODE for each method

        _resolve(path):
            join under root, resolve, and REFUSE to escape it
            # paths are partly built from external input (dates, sport names, source labels), so a
            # stray "../" must not be able to write outside the data directory

        write_bytes:
            mkdir parents
            write to a ".partial" neighbour, then os.replace() onto the target
            # a crash mid-write then leaves the PREVIOUS file intact rather than a truncated one that
            # looks complete. GCS gives this atomicity for free; a local filesystem does not.

        list_paths(prefix):  recursive, sorted, [] for a missing prefix
            # a source that landed nothing today is normal, not exceptional
    """


class GCSStorage:
    """Google Cloud Storage-backed.

    PSEUDOCODE

        __init__: import google.cloud.storage LAZILY, at construction
            # so a local run never needs the library, the CLI starts fast, and a missing dependency
            # fails where somebody asked for GCS rather than as an import error in an unrelated command

        write_bytes:  blob.upload_from_file(...)  -> "gs://bucket/path"
        list_paths:   client.list_blobs(bucket, prefix=...), sorted
    """


def build_storage(settings: Any, bucket: Optional[str] = None) -> Storage:
    """Pick a backend from configuration. The ONE place the choice is made.

    PSEUDOCODE:  GCSStorage(bucket or settings.bucket_lake) if settings.is_gcp else LocalStorage(...)
                 raise if TARGET=gcp with no bucket configured
    """
    raise NotImplementedError("pseudocode")


# --- Serialisation ------------------------------------------------------------------------------


def to_jsonl_gz(records: Iterable[Dict[str, Any]]) -> bytes:
    """Encode records as gzipped newline-delimited JSON. Used for the bronze landing zone.

    JSONL not a JSON array: readable one record at a time without parsing the whole file, and a
    truncated file still yields every complete record before the truncation.

    PSEUDOCODE

        gzip(mtime=0) over "\\n".join(json.dumps(record, sort_keys=True, default=isoformat))
        # mtime=0 AND sort_keys make the output byte-identical for identical input, so a re-run does
        # not churn object versions or defeat content-based change detection
    """
    raise NotImplementedError("pseudocode")


def to_parquet(table: Any, compression: str = "snappy") -> bytes:
    """Serialise an Arrow table to Parquet bytes. Shared by both ingestion paths.

    Shared deliberately, so the two paths cannot drift to different compression settings.

    In-memory buffering is safe **because of** the platform's 10,000-row export cap — worth knowing
    which upstream constraint the simplification rests on. Snappy over gzip: these files are read far
    more often than written, so cheap decode beats a smaller file.

    PSEUDOCODE:  pq.write_table(table, pa.BufferOutputStream(), compression) -> bytes
    """
    raise NotImplementedError("pseudocode")
