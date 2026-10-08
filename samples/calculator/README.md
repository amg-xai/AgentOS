# Calculator acceptance project

This project deliberately subtracts in `add`. Two of its three tests fail.
The mission should correct the implementation and preserve all test assertions.
No packages beyond the Python standard library are required.

From this directory, run `python -m unittest discover -v` to reproduce the bug.
This is an acceptance fixture, excluded from the application's backend test
suite. The AgentOS workflow fixes only its scratch copy; this source intentionally
retains the bug so the demonstration is repeatable.
