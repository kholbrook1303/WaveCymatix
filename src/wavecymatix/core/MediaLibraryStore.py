import logging
import os
import sqlite3
import threading
import time

from wavecymatix.lib.config import APP_ROOT

log = logging.getLogger()


class MediaLibraryStore:
    def __init__(
        self,
        media_type,
        section_config,
        supported_extensions,
        key_prefix,
        general_config=None,
        system_playlists=None,
        default_playlist=None,
    ):
        self.media_type = media_type
        self.section_config = section_config
        self.general_config = general_config or {}
        self.supported_extensions = tuple(ext.lower() for ext in supported_extensions)
        self.key_prefix = key_prefix
        # Paths are stored relative to APP_ROOT so moving/renaming the install directory doesn't break playlists.
        self.media_roots = (os.path.normpath(APP_ROOT),)
        if system_playlists is None:
            self.system_playlists = ("all", "favorites")
        else:
            self.system_playlists = tuple(system_playlists)

        default_db_path = os.path.join(APP_ROOT, "data", "media_library.db")
        configured_db_path = self.section_config.get("playlistdbpath")
        if not configured_db_path:
            configured_db_path = self.general_config.get("playlistdbpath")
        self.db_path = self.section_config.get(
            "playlistdbpath",
            configured_db_path or default_db_path,
        )
        if default_playlist is None:
            self.default_playlist = self.section_config.get(
                f"{self.key_prefix}.defaultplaylist",
                self.system_playlists[0] if self.system_playlists else "",
            )
        else:
            self.default_playlist = default_playlist

        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._initialize()

    def _table_exists(self, name):
        row = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return bool(row)

    def _initialize(self):
        with self._lock:
            self._create_schema()
            self._migrate_legacy_visual_schema_if_needed()
            self._ensure_video_window_columns()

            for name in self.system_playlists:
                self._ensure_system_playlist(name)

            if not self.system_playlists:
                self._conn.execute(
                    "UPDATE media_playlists SET is_system=0 WHERE media_type=?",
                    (self.media_type,),
                )
                self._conn.commit()

    def _create_schema(self):
        cur = self._conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS media_playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_type TEXT NOT NULL,
                name TEXT NOT NULL,
                is_system INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(media_type, name)
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS media_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_type TEXT NOT NULL,
                path TEXT NOT NULL,
                basename TEXT NOT NULL,
                extension TEXT NOT NULL,
                is_available INTEGER NOT NULL DEFAULT 1,
                last_seen_at REAL NOT NULL,
                video_start_sec REAL,
                video_stop_sec REAL,
                UNIQUE(media_type, path)
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS media_playlist_items (
                playlist_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                added_at REAL NOT NULL,
                PRIMARY KEY (playlist_id, item_id),
                FOREIGN KEY (playlist_id) REFERENCES media_playlists(id),
                FOREIGN KEY (item_id) REFERENCES media_items(id)
            )
            """
        )

        self._conn.commit()

    def _migrate_legacy_visual_schema_if_needed(self):
        if not self._table_exists("playlists"):
            return
        if not self._table_exists("visual_items"):
            return
        if not self._table_exists("playlist_items"):
            return

        migrated_flag = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if migrated_flag >= 2:
            return

        try:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO media_playlists (
                    id, media_type, name, is_system, created_at, updated_at
                )
                SELECT id, visual_type, name, is_system, created_at, updated_at
                FROM playlists
                """
            )
            self._conn.execute(
                """
                INSERT OR IGNORE INTO media_items (
                    id, media_type, path, basename, extension, is_available, last_seen_at
                )
                SELECT id, visual_type, path, basename, extension, is_available, last_seen_at
                FROM visual_items
                """
            )
            self._conn.execute(
                """
                INSERT OR IGNORE INTO media_playlist_items (
                    playlist_id, item_id, position, added_at
                )
                SELECT playlist_id, item_id, position, added_at
                FROM playlist_items
                """
            )
            self._conn.execute("PRAGMA user_version = 2")
            self._conn.commit()
            log.info("Migrated legacy visual playlist schema into media library schema")
        except Exception:
            self._conn.rollback()
            log.exception("Failed migrating legacy visual playlist schema")

    def _ensure_video_window_columns(self):
        rows = self._conn.execute("PRAGMA table_info(media_items)").fetchall()
        names = {row["name"] for row in rows}

        if "video_start_sec" not in names:
            self._conn.execute("ALTER TABLE media_items ADD COLUMN video_start_sec REAL")
        if "video_stop_sec" not in names:
            self._conn.execute("ALTER TABLE media_items ADD COLUMN video_stop_sec REAL")

        self._conn.commit()

    def _to_relative(self, path):
        if not self.media_roots or not path:
            return path

        best = None
        for root in self.media_roots:
            try:
                relative = os.path.relpath(path, root)
            except ValueError:
                continue

            if relative.startswith(".."):
                continue

            if best is None or len(relative) < len(best):
                best = relative

        return best if best is not None else path

    def _to_absolute(self, path):
        if not self.media_roots or not path or os.path.isabs(path):
            return path

        for root in self.media_roots:
            candidate = os.path.normpath(os.path.join(root, path))
            if os.path.exists(candidate):
                return candidate

        return os.path.normpath(os.path.join(self.media_roots[0], path))

    def close(self):
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                log.exception("Failed closing media library DB")

    def _ensure_system_playlist(self, name):
        now = time.time()
        self._conn.execute(
            """
            INSERT INTO media_playlists (media_type, name, is_system, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(media_type, name) DO UPDATE SET
                is_system = 1,
                updated_at = excluded.updated_at
            """,
            (self.media_type, name, now, now),
        )
        self._conn.commit()

    def _playlist_row(self, name):
        row = self._conn.execute(
            "SELECT id, name, is_system FROM media_playlists WHERE media_type=? AND name=?",
            (self.media_type, name),
        ).fetchone()
        return row

    def _playlist_id(self, name):
        row = self._playlist_row(name)
        return row["id"] if row else None

    def list_playlists(self):
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT name, is_system
                FROM media_playlists
                WHERE media_type=?
                """,
                (self.media_type,),
            ).fetchall()

            system_order = {name: idx for idx, name in enumerate(self.system_playlists)}
            ordered = sorted(
                rows,
                key=lambda row: (
                    0 if row["name"] in system_order else 1,
                    system_order.get(row["name"], 10_000),
                    str(row["name"]).lower(),
                ),
            )

            return [{"name": row["name"], "is_system": bool(row["is_system"])} for row in ordered]

    def create_playlist(self, name):
        if not name:
            return False

        safe_name = name.strip()
        if not safe_name:
            return False

        with self._lock:
            now = time.time()
            self._conn.execute(
                """
                INSERT INTO media_playlists (media_type, name, is_system, created_at, updated_at)
                VALUES (?, ?, 0, ?, ?)
                ON CONFLICT(media_type, name) DO NOTHING
                """,
                (self.media_type, safe_name, now, now),
            )
            self._conn.commit()
            return True

    def delete_playlist(self, name):
        if not name or name in self.system_playlists:
            return False

        with self._lock:
            row = self._playlist_row(name)
            if not row:
                return False

            if row["is_system"]:
                return False

            self._conn.execute("DELETE FROM media_playlist_items WHERE playlist_id=?", (row["id"],))
            self._conn.execute(
                "DELETE FROM media_playlists WHERE id=? AND media_type=?",
                (row["id"], self.media_type),
            )
            self._conn.commit()
            return True

    def sync_library(self, discovered_paths):
        now = time.time()
        normalized = []

        for raw_path in discovered_paths:
            path = self._normalize_supported_path(raw_path)
            if path:
                normalized.append(path)

        unique_paths = sorted(set(normalized))

        with self._lock:
            self._conn.execute(
                "UPDATE media_items SET is_available=0 WHERE media_type=?",
                (self.media_type,),
            )

            for path in unique_paths:
                self._upsert_media_item(path, now=now, available=True)

            self._conn.execute(
                """
                DELETE FROM media_playlist_items
                WHERE item_id IN (
                    SELECT id FROM media_items
                    WHERE media_type=? AND is_available=0
                )
                """,
                (self.media_type,),
            )

            if "all" in self.system_playlists:
                all_playlist_id = self._playlist_id("all")
                self._conn.execute("DELETE FROM media_playlist_items WHERE playlist_id=?", (all_playlist_id,))

                rows = self._conn.execute(
                    """
                    SELECT id
                    FROM media_items
                    WHERE media_type=? AND is_available=1
                    ORDER BY basename COLLATE NOCASE ASC, path COLLATE NOCASE ASC
                    """,
                    (self.media_type,),
                ).fetchall()

                for position, row in enumerate(rows):
                    self._conn.execute(
                        """
                        INSERT INTO media_playlist_items (playlist_id, item_id, position, added_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (all_playlist_id, row["id"], position, now),
                    )

            self._conn.commit()

    def _normalize_supported_path(self, raw_path):
        if not raw_path:
            return None

        full_path = os.path.normpath(raw_path)
        ext = os.path.splitext(full_path)[1].lower()
        if self.supported_extensions and ext not in self.supported_extensions:
            return None

        return self._to_relative(full_path)

    def _upsert_media_item(self, path, now=None, available=None):
        normalized = self._normalize_supported_path(path)
        if not normalized:
            return None

        now = now if now is not None else time.time()
        base = os.path.basename(normalized)
        ext = os.path.splitext(normalized)[1].lower()
        if available is None:
            available = os.path.exists(self._to_absolute(normalized))

        self._conn.execute(
            """
            INSERT INTO media_items (
                media_type, path, basename, extension, is_available, last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(media_type, path) DO UPDATE SET
                basename=excluded.basename,
                extension=excluded.extension,
                is_available=excluded.is_available,
                last_seen_at=excluded.last_seen_at
            """,
            (self.media_type, normalized, base, ext, 1 if available else 0, now),
        )

        row = self._conn.execute(
            "SELECT id FROM media_items WHERE media_type=? AND path=?",
            (self.media_type, normalized),
        ).fetchone()
        return row["id"] if row else None

    def playlist_size(self, name):
        with self._lock:
            playlist_id = self._playlist_id(name)
            if playlist_id is None:
                return 0

            row = self._conn.execute(
                "SELECT COUNT(*) AS count FROM media_playlist_items WHERE playlist_id=?",
                (playlist_id,),
            ).fetchone()
            return int(row["count"]) if row else 0

    def resolve_startup_playlist(self):
        with self._lock:
            configured = (self.default_playlist or "").strip()
            if configured:
                if self._playlist_id(configured) is not None and self.playlist_size(configured) > 0:
                    return configured

            for system_name in self.system_playlists:
                if self.playlist_size(system_name) > 0:
                    return system_name

            row = self._conn.execute(
                """
                SELECT name
                FROM media_playlists
                WHERE media_type=?
                ORDER BY name COLLATE NOCASE ASC
                LIMIT 1
                """,
                (self.media_type,),
            ).fetchone()
            if row:
                return row["name"]

            return self.system_playlists[0] if self.system_playlists else ""

    def get_playlist_items(self, name):
        with self._lock:
            playlist_id = self._playlist_id(name)
            if playlist_id is None:
                return []

            rows = self._conn.execute(
                """
                SELECT mi.path
                FROM media_playlist_items mpi
                INNER JOIN media_items mi ON mi.id = mpi.item_id
                WHERE mpi.playlist_id=? AND mi.media_type=? AND mi.is_available=1
                ORDER BY mpi.position ASC
                """,
                (playlist_id, self.media_type),
            ).fetchall()

            return [self._to_absolute(row["path"]) for row in rows]

    def add_items_to_playlist(self, playlist_name, paths, insert_at=None):
        if not paths:
            return 0

        with self._lock:
            playlist_id = self._playlist_id(playlist_name)
            if playlist_id is None:
                return 0

            existing_ids = [
                row["item_id"]
                for row in self._conn.execute(
                    """
                    SELECT item_id
                    FROM media_playlist_items
                    WHERE playlist_id=?
                    ORDER BY position ASC
                    """,
                    (playlist_id,),
                ).fetchall()
            ]

            added_ids = []
            now = time.time()
            for path in paths:
                item_id = self._upsert_media_item(path, now=now)
                if item_id is None:
                    continue
                if item_id in existing_ids or item_id in added_ids:
                    continue
                added_ids.append(item_id)

            if not added_ids:
                return 0

            if insert_at is None:
                insert_at = len(existing_ids)
            insert_at = max(0, min(int(insert_at), len(existing_ids)))

            new_order = existing_ids[:insert_at] + added_ids + existing_ids[insert_at:]
            self._rewrite_playlist_order(playlist_id, new_order)
            return len(added_ids)

    def remove_items_from_playlist(self, playlist_name, paths):
        if not paths:
            return 0

        with self._lock:
            playlist_id = self._playlist_id(playlist_name)
            if playlist_id is None:
                return 0

            removed = 0
            for path in paths:
                normalized = self._to_relative(os.path.normpath(path))
                self._conn.execute(
                    """
                    DELETE FROM media_playlist_items
                    WHERE playlist_id=?
                    AND item_id = (
                        SELECT id FROM media_items
                        WHERE media_type=? AND path=?
                    )
                    """,
                    (playlist_id, self.media_type, normalized),
                )
                removed += self._conn.execute("SELECT changes() AS changes").fetchone()["changes"]

            self._conn.commit()
            self._normalize_positions(playlist_id)
            return int(removed)

    def remove_indices_from_playlist(self, playlist_name, indices):
        if not indices:
            return 0

        with self._lock:
            playlist_id = self._playlist_id(playlist_name)
            if playlist_id is None:
                return 0

            rows = self._conn.execute(
                """
                SELECT item_id
                FROM media_playlist_items
                WHERE playlist_id=?
                ORDER BY position ASC
                """,
                (playlist_id,),
            ).fetchall()
            order = [row["item_id"] for row in rows]

            to_remove = {idx for idx in indices if 0 <= idx < len(order)}
            if not to_remove:
                return 0

            new_order = [item_id for idx, item_id in enumerate(order) if idx not in to_remove]
            removed = len(order) - len(new_order)
            self._rewrite_playlist_order(playlist_id, new_order)
            return removed

    def move_item_in_playlist(self, playlist_name, src_index, dst_index):
        with self._lock:
            playlist_id = self._playlist_id(playlist_name)
            if playlist_id is None:
                return False

            rows = self._conn.execute(
                """
                SELECT item_id
                FROM media_playlist_items
                WHERE playlist_id=?
                ORDER BY position ASC
                """,
                (playlist_id,),
            ).fetchall()
            order = [row["item_id"] for row in rows]

            if not order:
                return False
            if src_index < 0 or src_index >= len(order):
                return False

            dst_index = max(0, min(int(dst_index), len(order) - 1))
            if src_index == dst_index:
                return True

            item_id = order.pop(src_index)
            order.insert(dst_index, item_id)
            self._rewrite_playlist_order(playlist_id, order)
            return True

    def replace_playlist_items(self, playlist_name, paths):
        with self._lock:
            playlist_id = self._playlist_id(playlist_name)
            if playlist_id is None:
                return False

            ordered_ids = []
            now = time.time()
            for path in paths:
                item_id = self._upsert_media_item(path, now=now)
                if item_id is None:
                    continue
                if item_id in ordered_ids:
                    continue
                ordered_ids.append(item_id)

            self._rewrite_playlist_order(playlist_id, ordered_ids)
            return True

    def _rewrite_playlist_order(self, playlist_id, item_ids):
        now = time.time()
        self._conn.execute("DELETE FROM media_playlist_items WHERE playlist_id=?", (playlist_id,))

        for position, item_id in enumerate(item_ids):
            self._conn.execute(
                """
                INSERT INTO media_playlist_items (playlist_id, item_id, position, added_at)
                VALUES (?, ?, ?, ?)
                """,
                (playlist_id, item_id, position, now),
            )

        self._conn.commit()

    def _normalize_positions(self, playlist_id):
        rows = self._conn.execute(
            """
            SELECT item_id
            FROM media_playlist_items
            WHERE playlist_id=?
            ORDER BY position ASC
            """,
            (playlist_id,),
        ).fetchall()

        for index, row in enumerate(rows):
            self._conn.execute(
                "UPDATE media_playlist_items SET position=? WHERE playlist_id=? AND item_id=?",
                (index, playlist_id, row["item_id"]),
            )

        self._conn.commit()

    def add_items_to_favorites(self, paths):
        if "favorites" not in self.system_playlists:
            return 0
        return self.add_items_to_playlist("favorites", paths)

    def remove_items_from_favorites(self, paths):
        if "favorites" not in self.system_playlists:
            return 0
        return self.remove_items_from_playlist("favorites", paths)

    def is_favorite(self, path):
        if "favorites" not in self.system_playlists:
            return False

        with self._lock:
            favorites_id = self._playlist_id("favorites")
            if favorites_id is None:
                return False

            row = self._conn.execute(
                """
                SELECT 1
                FROM media_playlist_items
                WHERE playlist_id=?
                AND item_id=(
                    SELECT id FROM media_items WHERE media_type=? AND path=?
                )
                """,
                (favorites_id, self.media_type, self._to_relative(os.path.normpath(path))),
            ).fetchone()
            return bool(row)

    def set_video_item_window(self, path, start_sec=None, stop_sec=None):
        with self._lock:
            item_id = self._upsert_media_item(path)
            if item_id is None:
                return False

            self._conn.execute(
                """
                UPDATE media_items
                SET video_start_sec=?, video_stop_sec=?
                WHERE id=?
                """,
                (start_sec, stop_sec, item_id),
            )
            self._conn.commit()
            return True

    def get_video_item_window(self, path):
        with self._lock:
            row = self._conn.execute(
                """
                SELECT video_start_sec, video_stop_sec
                FROM media_items
                WHERE media_type=? AND path=?
                """,
                (self.media_type, self._to_relative(os.path.normpath(path))),
            ).fetchone()
            if not row:
                return None
            return {
                "start_sec": row["video_start_sec"],
                "stop_sec": row["video_stop_sec"],
            }
