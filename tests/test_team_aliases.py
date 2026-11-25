"""Offline team-alias tests for the manual shadow runner."""
import re
import unittest
from totals_shadow import find_team


def key(value):
    return re.sub("[^a-z0-9]", "", value.lower())


class TeamAliasTests(unittest.TestCase):
    def test_exact_match_wins(self):
        index = {"losangelesclippers": "9", "laclippers": "3", "clippers": "3"}
        self.assertEqual(find_team(index, "Los Angeles Clippers", "NBA", key), "9")

    def test_clippers_alias_after_exact_miss(self):
        self.assertEqual(find_team({"laclippers": "3"}, "Los Angeles Clippers", "NBA", key), "3")

    def test_short_name_alias_after_exact_miss(self):
        self.assertEqual(find_team({"clippers": "3"}, "Los Angeles Clippers", "NBA", key), "3")

    def test_unknown_team_still_unmatched(self):
        self.assertIsNone(find_team({"laclippers": "3"}, "Los Angeles Lakers", "NBA", key))

    def test_alias_is_league_specific(self):
        self.assertIsNone(find_team({"laclippers": "3"}, "Los Angeles Clippers", "NFL", key))


if __name__ == "__main__":
    unittest.main()
