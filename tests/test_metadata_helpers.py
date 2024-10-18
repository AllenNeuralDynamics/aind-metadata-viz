"""Test the main app code"""

import unittest
import json
from pydantic import BaseModel
from aind_metadata_viz.metadata_helpers import _metadata_present_helper, _metadata_valid_helper


class TestApp(unittest.TestCase):
    """Test main app"""

    def test_metadata_present_helper(self):
        """Test metadata present helper"""
        present0 = _metadata_present_helper('abc')
        present1 = _metadata_present_helper(['list'])
        present2 = _metadata_present_helper({'key': 1})
        missing0 = _metadata_present_helper(None)
        missing1 = _metadata_present_helper('')
        missing2 = _metadata_present_helper([])
        missing3 = _metadata_present_helper({})

        self.assertEqual(present0, 'present')
        self.assertEqual(present1, 'present')
        self.assertEqual(present2, 'present')
        self.assertEqual(missing0, 'absent')
        self.assertEqual(missing1, 'absent')
        self.assertEqual(missing2, 'absent')
        self.assertEqual(missing3, 'absent')

    def test_metadata_valid_helper(self):
        """Test metadata valid helper"""

        class TestClass(BaseModel):
            schema_version: str = "0.0.0"
            field: str

        file = 'quality_control'
        json_dict = {file: TestClass(field="value").model_dump()}
        mapping = {file: TestClass}

        result = _metadata_valid_helper(file, json_dict, mapping)
        print(result)
        self.assertEqual(result, True)

        result = _metadata_valid_helper(file, {file: "none"}, mapping)
        self.assertEqual(result, False)


if __name__ == "__main__":
    unittest.main()
