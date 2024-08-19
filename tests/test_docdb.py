"""Example test template."""

import unittest

from aind_metadata_viz.docdb import get_subjects, get_sessions, get_all


class DocDBTest(unittest.TestCase):
    """Test the DocDB calls"""
    # def setUp(self):

    def test_get_subjects(self):
        """Get the subjects list, check that some known subjects are in it"""
        self.assertIn(596930, get_subjects())

    def test_get_sessions(self):
        """Get data from the test subject's sessions"""
        self.assertEqual(1, len(get_sessions(596930)))

    def test_get_all(self):
        """Test all sessions"""
        data = get_all(test_mode=True)
        first_ten_subjects = ['271246', '666612', '673594', '719093', '651474', '666612', '666612', '651474', '719093', '673594']
        subj_id = [dat['subject']['subject_id'] for dat in data]

        self.assertEqual(subj_id, first_ten_subjects)


if __name__ == "__main__":
    unittest.main()
