from __future__ import annotations

import unittest

from jsonc_sort_keys import JsoncSyntaxError, sort_jsonc


class SortJsoncTests(unittest.TestCase):
    def test_sorts_basic_object(self) -> None:
        self.assertEqual(
            sort_jsonc('{"b":2,"a":1}'),
            '{"a":1,"b":2}',
        )

    def test_sorts_nested_objects_but_not_arrays(self) -> None:
        source = """[
  {"b": 2, "a": 1},
  {"d": 4, "c": 3}
]
"""
        expected = """[
  {"a": 1, "b": 2},
  {"c": 3, "d": 4}
]
"""
        self.assertEqual(sort_jsonc(source), expected)

    def test_carries_full_line_comments_with_members(self) -> None:
        source = """{
  // beta
  "b": 2,

  // alpha
  "a": 1,
}
"""
        expected = """{
  // alpha
  "a": 1,

  // beta
  "b": 2
}
"""
        self.assertEqual(sort_jsonc(source), expected)

    def test_keeps_inline_comments_with_member_value(self) -> None:
        source = """{
  "b": 2, // beta
  "a": 1 // alpha
}
"""
        expected = """{
  "a": 1, // alpha
  "b": 2 // beta
}
"""
        self.assertEqual(sort_jsonc(source), expected)

    def test_removes_object_trailing_comma(self) -> None:
        source = """{
  "a": 1,
}
"""
        expected = """{
  "a": 1
}
"""
        self.assertEqual(sort_jsonc(source), expected)

    def test_removes_array_trailing_comma_without_reordering(self) -> None:
        source = """[
  "b",
  "a",
]
"""
        expected = """[
  "b",
  "a"
]
"""
        self.assertEqual(sort_jsonc(source), expected)

    def test_sorts_by_decoded_key_stably(self) -> None:
        self.assertEqual(
            sort_jsonc('{"\\u0062":1,"a":2,"b":3}'),
            '{"a":2,"\\u0062":1,"b":3}',
        )

    def test_accepts_comments_around_root(self) -> None:
        source = '// leading\n{"b":2,"a":1}\n// trailing\n'
        expected = '// leading\n{"a":1,"b":2}\n// trailing\n'
        self.assertEqual(sort_jsonc(source), expected)

    def test_rejects_invalid_jsonc(self) -> None:
        with self.assertRaises(JsoncSyntaxError):
            sort_jsonc('{"a": 1 "b": 2}')

    def test_rejects_unterminated_block_comment(self) -> None:
        with self.assertRaises(JsoncSyntaxError):
            sort_jsonc("{/* nope")


if __name__ == "__main__":
    unittest.main()
