"""Getting external material into text: fetch, extract, chunk. No database in here."""


class IngestError(Exception):
    """A failure the user can understand and act on (shown as the source's error)."""
