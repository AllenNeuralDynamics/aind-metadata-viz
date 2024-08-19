"""Test the main app code"""

import unittest
from aind_metadata_viz.metadata_helpers import check_present, process_present_dict, process_present_list


class TestApp(unittest.TestCase):
    """Test main app"""

    def setUp(self) -> None:
        self.dict = {"test1": None,
                     "test2": "",
                     "test3": {},
                     "test4": [],
                     "test5": 'actual data'}
        self.expected_fields = ['test1', 'test2', 'test3', 'test4', 'test5', 'meow']

        return super().setUp()

    def test_check_present(self):
        """Test the check_present function"""
        
        self.assertFalse(check_present("test1", self.dict))
        self.assertFalse(check_present("test2", self.dict))
        self.assertFalse(check_present("test3", self.dict))
        self.assertFalse(check_present("test4", self.dict))

        self.assertTrue(check_present("test5", self.dict))

    def test_process_present_dict(self):
        """Test the process_present_dict function"""
        out_test = process_present_dict(self.dict, self.expected_fields)
        out = {'test1': False,
               'test2': False,
               "test3": False,
               "test4": False,
               "test5": True,
               'meow': False}

        self.assertEqual(out, out_test)

    def test_process_present(self):
        """Test that process runs properly on a list"""
        data_list = [self.dict, self.dict]
        out = {'test1': False,
               'test2': False,
               "test3": False,
               "test4": False,
               "test5": True,
               'meow': False}

        processed_list = process_present_list(data_list, self.expected_fields)
        out_list = [out, out]

        self.assertEqual(processed_list, out_list)


if __name__ == "__main__":
    unittest.main()
