from __future__ import annotations

import argparse
from datetime import date
from types import SimpleNamespace
import unittest

from seoboy.cli import _gsc_previous_period


class PreviousPeriodTests(unittest.TestCase):
    def setUp(self):
        self.parser = argparse.ArgumentParser()
        self.start = date(2026, 10, 23)
        self.end = date(2026, 11, 19)

    def _args(self, previous_start=None, previous_end=None, compare=True):
        return SimpleNamespace(
            gsc_previous_start=previous_start,
            gsc_previous_end=previous_end,
            gsc_compare=compare,
        )

    def test_accepts_explicit_equal_period(self):
        args = self._args(date(2026, 9, 25), date(2026, 10, 22))
        period = _gsc_previous_period(args, self.start, self.end, self.parser)
        self.assertEqual(period, (date(2026, 9, 25), date(2026, 10, 22)))

    def test_requires_both_dates(self):
        args = self._args(date(2026, 9, 25), None)
        with self.assertRaises(SystemExit):
            _gsc_previous_period(args, self.start, self.end, self.parser)

    def test_requires_compare(self):
        args = self._args(date(2026, 9, 25), date(2026, 10, 22), compare=False)
        with self.assertRaises(SystemExit):
            _gsc_previous_period(args, self.start, self.end, self.parser)

    def test_rejects_unequal_length(self):
        args = self._args(date(2026, 9, 1), date(2026, 10, 22))
        with self.assertRaises(SystemExit):
            _gsc_previous_period(args, self.start, self.end, self.parser)

    def test_rejects_overlap(self):
        args = self._args(date(2026, 9, 26), date(2026, 10, 23))
        with self.assertRaises(SystemExit):
            _gsc_previous_period(args, self.start, self.end, self.parser)


if __name__ == "__main__":
    unittest.main()
