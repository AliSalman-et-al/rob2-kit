# Separate canonical and derivative SQLite stores

Canonical scientific and workflow records remain in one SQLite database.
Rebuildable page text, FTS data, and render metadata remain in a separate SQLite
database. The server can delete and rebuild derivative data without exposing
Canonical state to cache loss or corruption.
