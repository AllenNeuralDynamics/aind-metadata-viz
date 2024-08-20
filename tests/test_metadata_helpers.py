"""Test the main app code"""

import unittest
from aind_metadata_viz.metadata_helpers import (
    check_present,
    process_present_dict,
    process_present_list,
)


class TestApp(unittest.TestCase):
    """Test main app"""

    def setUp(self) -> None:
        self.dict = {
            "test1": None,
            "test2": "",
            "test3": {},
            "test4": [],
            "test5": "actual data",
            "test6": 1,
            "test7": {"actual key": "actual value"},
            "test8": object,
        }
        self.expected_fields = [
            "test1",
            "test2",
            "test3",
            "test4",
            "test5",
            "test6",
            "test7",
            "test8",
            "meow",
        ]
        self.expected_out = {
            "test1": False,
            "test2": False,
            "test3": False,
            "test4": False,
            "test5": True,
            "test6": True,
            "test7": True,
            "test8": True,
            "meow": False,
        }

        return super().setUp()

    def test_check_present(self):
        """Test the check_present function"""
        self.assertFalse(check_present("test1", self.dict))
        self.assertFalse(check_present("test2", self.dict))
        self.assertFalse(check_present("test3", self.dict))
        self.assertFalse(check_present("test4", self.dict))

        self.assertTrue(check_present("test5", self.dict))
        self.assertTrue(check_present("test6", self.dict))
        self.assertTrue(check_present("test7", self.dict))
        self.assertTrue(check_present("test8", self.dict))

        self.assertFalse(check_present("test8", self.dict, check_present=False))

    def test_process_present_dict(self):
        """Test the process_present_dict function"""
        out_test = process_present_dict(self.dict, self.expected_fields)

        self.assertEqual(self.expected_out, out_test)

    def test_process_present(self):
        """Test that process runs properly on a list"""
        data_list = [self.dict, self.dict]

        processed_list = process_present_list(data_list, self.expected_fields)
        out_list = [self.expected_out, self.expected_out]

        self.assertEqual(processed_list, out_list)


if __name__ == "__main__":
    unittest.main()
