"""
5 seed problems. Each has 3 visible + 5 hidden test cases.
test_cases: shown to the player after Run.
hidden_test_cases: only used for Submit (final verdict).
"""

PROBLEMS = [
    {
        "slug": "two-sum",
        "title": "Two Sum",
        "difficulty": "easy",
        "statement_md": """## Two Sum

Given an array of integers `nums` and an integer `target`, return *indices of the two numbers that add up to `target`*.

You may assume that each input has **exactly one solution**, and you may not use the same element twice.

**Example 1:**
```
Input: nums = [2,7,11,15], target = 9
Output: [0,1]
```

**Example 2:**
```
Input: nums = [3,2,4], target = 6
Output: [1,2]
```

**Constraints:**
- 2 <= nums.length <= 10^4
- -10^9 <= nums[i] <= 10^9
- Only one valid answer exists.

**Your function signature:**
```python
def two_sum(nums: list[int], target: int) -> list[int]:
```
""",
        "test_cases": [
            {"input": "[2,7,11,15]\n9", "expected": "[0, 1]"},
            {"input": "[3,2,4]\n6", "expected": "[1, 2]"},
            {"input": "[3,3]\n6", "expected": "[0, 1]"},
        ],
        "hidden_test_cases": [
            {"input": "[1,2,3,4,5]\n9", "expected": "[3, 4]"},
            {"input": "[-1,-2,-3,-4,-5]\n-8", "expected": "[2, 4]"},
            {"input": "[0,4,3,0]\n0", "expected": "[0, 3]"},
            {"input": "[2,5,5,11]\n10", "expected": "[1, 2]"},
            {"input": "[1,3,4,2]\n6", "expected": "[2, 3]"},
        ],
        "reference_solution": """def two_sum(nums, target):
    seen = {}
    for i, n in enumerate(nums):
        if target - n in seen:
            return [seen[target - n], i]
        seen[n] = i
""",
    },
    {
        "slug": "valid-parentheses",
        "title": "Valid Parentheses",
        "difficulty": "easy",
        "statement_md": """## Valid Parentheses

Given a string `s` containing just the characters `(`, `)`, `{`, `}`, `[` and `]`, determine if the input string is valid.

A string is valid if:
- Open brackets are closed by the same type of brackets.
- Open brackets are closed in the correct order.
- Every close bracket has a corresponding open bracket.

**Example 1:** `s = "()"` → `True`
**Example 2:** `s = "()[]{}"` → `True`
**Example 3:** `s = "(]"` → `False`

**Your function signature:**
```python
def is_valid(s: str) -> bool:
```
""",
        "test_cases": [
            {"input": "()", "expected": "True"},
            {"input": "()[]{}", "expected": "True"},
            {"input": "(]", "expected": "False"},
        ],
        "hidden_test_cases": [
            {"input": "([)]", "expected": "False"},
            {"input": "{[]}", "expected": "True"},
            {"input": "", "expected": "True"},
            {"input": "((", "expected": "False"},
            {"input": "]", "expected": "False"},
        ],
        "reference_solution": """def is_valid(s):
    stack = []
    mapping = {')': '(', ']': '[', '}': '{'}
    for c in s:
        if c in '([{':
            stack.append(c)
        elif not stack or stack[-1] != mapping[c]:
            return False
        else:
            stack.pop()
    return not stack
""",
    },
    {
        "slug": "longest-substring-without-repeating",
        "title": "Longest Substring Without Repeating Characters",
        "difficulty": "medium",
        "statement_md": """## Longest Substring Without Repeating Characters

Given a string `s`, find the length of the **longest substring** without repeating characters.

**Example 1:** `s = "abcabcbb"` → `3` (substring `"abc"`)
**Example 2:** `s = "bbbbb"` → `1`
**Example 3:** `s = "pwwkew"` → `3` (substring `"wke"`)

**Your function signature:**
```python
def length_of_longest_substring(s: str) -> int:
```
""",
        "test_cases": [
            {"input": "abcabcbb", "expected": "3"},
            {"input": "bbbbb", "expected": "1"},
            {"input": "pwwkew", "expected": "3"},
        ],
        "hidden_test_cases": [
            {"input": "", "expected": "0"},
            {"input": " ", "expected": "1"},
            {"input": "au", "expected": "2"},
            {"input": "dvdf", "expected": "3"},
            {"input": "abcdefghijklmnopqrstuvwxyz", "expected": "26"},
        ],
        "reference_solution": """def length_of_longest_substring(s):
    left = 0
    max_len = 0
    char_index = {}
    for right, c in enumerate(s):
        if c in char_index and char_index[c] >= left:
            left = char_index[c] + 1
        char_index[c] = right
        max_len = max(max_len, right - left + 1)
    return max_len
""",
    },
    {
        "slug": "merge-intervals",
        "title": "Merge Intervals",
        "difficulty": "medium",
        "statement_md": """## Merge Intervals

Given an array of `intervals` where `intervals[i] = [starti, endi]`, merge all overlapping intervals.

**Example 1:**
```
Input: [[1,3],[2,6],[8,10],[15,18]]
Output: [[1,6],[8,10],[15,18]]
```

**Example 2:**
```
Input: [[1,4],[4,5]]
Output: [[1,5]]
```

**Your function signature:**
```python
def merge(intervals: list[list[int]]) -> list[list[int]]:
```
""",
        "test_cases": [
            {"input": "[[1,3],[2,6],[8,10],[15,18]]", "expected": "[[1, 6], [8, 10], [15, 18]]"},
            {"input": "[[1,4],[4,5]]", "expected": "[[1, 5]]"},
            {"input": "[[1,4],[0,4]]", "expected": "[[0, 4]]"},
        ],
        "hidden_test_cases": [
            {"input": "[[1,4],[0,0]]", "expected": "[[0, 0], [1, 4]]"},
            {"input": "[[1,4],[2,3]]", "expected": "[[1, 4]]"},
            {"input": "[[1,4],[5,6]]", "expected": "[[1, 4], [5, 6]]"},
            {"input": "[[1,4],[0,2],[3,5]]", "expected": "[[0, 5]]"},
            {"input": "[[2,3],[4,5],[6,7],[8,9],[1,10]]", "expected": "[[1, 10]]"},
        ],
        "reference_solution": """def merge(intervals):
    intervals.sort(key=lambda x: x[0])
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged
""",
    },
    {
        "slug": "climbing-stairs",
        "title": "Climbing Stairs",
        "difficulty": "easy",
        "statement_md": """## Climbing Stairs

You are climbing a staircase. It takes `n` steps to reach the top. Each time you can climb `1` or `2` steps. In how many distinct ways can you climb to the top?

**Example 1:** `n = 2` → `2` (1+1 or 2)
**Example 2:** `n = 3` → `3` (1+1+1, 1+2, 2+1)

**Your function signature:**
```python
def climb_stairs(n: int) -> int:
```
""",
        "test_cases": [
            {"input": "2", "expected": "2"},
            {"input": "3", "expected": "3"},
            {"input": "5", "expected": "8"},
        ],
        "hidden_test_cases": [
            {"input": "1", "expected": "1"},
            {"input": "4", "expected": "5"},
            {"input": "10", "expected": "89"},
            {"input": "38", "expected": "63245986"},
            {"input": "45", "expected": "1836311903"},
        ],
        "reference_solution": """def climb_stairs(n):
    a, b = 1, 1
    for _ in range(n - 1):
        a, b = b, a + b
    return b
""",
    },
]


# Wrapper scripts per problem slug — wraps user code + calls function with test input
WRAPPERS = {
    "two-sum": """import sys, ast
{user_code}
line1, line2 = sys.stdin.read().strip().split('\\n')
nums = ast.literal_eval(line1)
target = int(line2)
print(sorted(two_sum(nums, target)))
""",
    "valid-parentheses": """import sys
{user_code}
s = sys.stdin.read().strip()
print(is_valid(s))
""",
    "longest-substring-without-repeating": """import sys
{user_code}
s = sys.stdin.read().strip()
print(length_of_longest_substring(s))
""",
    "merge-intervals": """import sys, ast
{user_code}
intervals = ast.literal_eval(sys.stdin.read().strip())
print(merge(intervals))
""",
    "climbing-stairs": """import sys
{user_code}
n = int(sys.stdin.read().strip())
print(climb_stairs(n))
""",
}
