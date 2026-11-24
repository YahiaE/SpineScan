import unittest
from types import SimpleNamespace
from unittest import mock

from benchmark_discogs import ValidationRatePacer, reset_probe_state


class FakeSupabase:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        if name != "albums":
            raise AssertionError(f"Unexpected table: {name}")
        return FakeAlbumTable(self)


class FakeAlbumTable:
    def __init__(self, supabase):
        self.supabase = supabase
        self.operation = None
        self.filters = {}

    def select(self, _columns):
        self.operation = "select"
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def execute(self):
        matches = [
            row
            for row in self.supabase.rows
            if all(row.get(column) == value for column, value in self.filters.items())
        ]
        if self.operation == "delete":
            self.supabase.rows = [
                row for row in self.supabase.rows if row not in matches
            ]
            return SimpleNamespace(data=[])
        return SimpleNamespace(data=[dict(row) for row in matches])


class FakeRedis:
    def __init__(self, keys):
        self.keys = set(keys)
        self.removed_from_index = []

    def delete(self, *keys):
        for key in keys:
            self.keys.discard(key)

    def zrem(self, index_key, member):
        self.removed_from_index.append((index_key, member))

    def exists(self, *keys):
        return sum(key in self.keys for key in keys)


class ResetProbeStateTests(unittest.TestCase):
    def setUp(self):
        self.normalized_key = "radiohead::okcomputer"
        self.pending_key = "pending:" + self.normalized_key
        self.result_key = "result:" + self.normalized_key
        self.pending_index_key = "pending-index"
        self.supabase = FakeSupabase(
            [
                {"normalized_key": self.normalized_key, "discogs_release_id": 123},
                {"normalized_key": "other::album", "discogs_release_id": 456},
            ]
        )
        self.redis_conn = FakeRedis([self.pending_key, self.result_key])
        self.cleanup_keys = (
            lambda key: "pending:" + key,
            lambda key: "result:" + key,
        )

    def test_removes_only_the_matching_probe_row_and_lookup_markers(self):
        reset_probe_state(
            self.supabase,
            self.redis_conn,
            self.normalized_key,
            123,
            self.cleanup_keys,
            self.pending_index_key,
        )

        self.assertEqual(
            self.supabase.rows,
            [{"normalized_key": "other::album", "discogs_release_id": 456}],
        )
        self.assertEqual(self.redis_conn.keys, set())
        self.assertEqual(
            self.redis_conn.removed_from_index,
            [(self.pending_index_key, self.pending_key)],
        )

    def test_refuses_to_remove_a_probe_row_with_a_different_release_id(self):
        with self.assertRaisesRegex(RuntimeError, "changed unexpectedly"):
            reset_probe_state(
                self.supabase,
                self.redis_conn,
                self.normalized_key,
                999,
                self.cleanup_keys,
                self.pending_index_key,
            )

        self.assertEqual(len(self.supabase.rows), 2)
        self.assertEqual(self.redis_conn.keys, {self.pending_key, self.result_key})
        self.assertEqual(self.redis_conn.removed_from_index, [])


class ValidationRatePacerTests(unittest.TestCase):
    def test_waits_for_a_new_window_after_the_request_limit(self):
        clock = [5.0]

        def fake_sleep(duration):
            clock[0] += duration

        with mock.patch(
            "benchmark_discogs.time.time", side_effect=lambda: clock[0]
        ), mock.patch("benchmark_discogs.time.sleep", side_effect=fake_sleep) as sleep:
            pacer = ValidationRatePacer(request_limit=2, window_seconds=60)
            pacer.wait_for_slot()
            pacer.wait_for_slot()
            self.assertEqual(sleep.call_count, 0)

            pacer.wait_for_slot()

            self.assertEqual(sleep.call_count, 1)
            self.assertGreaterEqual(clock[0], 60)

            pacer.wait_for_slot()
            self.assertEqual(sleep.call_count, 1)


if __name__ == "__main__":
    unittest.main()
