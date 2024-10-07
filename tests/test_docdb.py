"""Example test template."""

import unittest

from aind_metadata_viz.docdb import get_subjects


class DocDBTest(unittest.TestCase):
    """Test the DocDB calls"""

    # def setUp(self):

    def test_get_all(self):
        """Test all sessions"""
        data = get_all(test_mode=True)
        first_ten_subjects = [
            "271246",
            "666612",
            "673594",
            "719093",
            "651474",
            "666612",
            "666612",
            "651474",
            "719093",
            "673594",
        ]
        subj_id = [dat["subject"]["subject_id"] for dat in data]

        self.assertEqual(subj_id, first_ten_subjects)


if __name__ == "__main__":
    unittest.main()
