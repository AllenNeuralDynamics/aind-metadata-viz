"""Example test template."""

import unittest

from aind_metadata_viz.docdb import Database, EXPECTED_FILES


class DocDBDatabaseTest(unittest.TestCase):

    def setUp(self) -> None:
        self.db = Database(test_mode=True)

        return super().setUp()

    def test_filtered_all(self):
        """Test all sessions"""
        data = self.db.data_filtered
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

    def test_filtered_ecephys(self):
        """Test ecephys filtering"""
        self.db.modality_filter = "ecephys"
        data = self.db.data_filtered

        ecephys_subjects = ["719093", "719093"]
        subj_id = [dat["subject"]["subject_id"] for dat in data]

        self.assertEqual(subj_id, ecephys_subjects)

    def test_filtered_files(self):
        """Test filtering by file"""
        mid_len = [0, 10, 0, 10, 10, 0, 10, 2, 10]

        for i, file in enumerate(EXPECTED_FILES):
            self.db.set_file(file)

            self.assertEqual(len(self.db.mid_list), mid_len[i])

    def test_derived(self):
        """Test filtering for derived"""

        self.db.derived_filter = True

        self.assertEqual(len(self.db.data_filtered), 0)
