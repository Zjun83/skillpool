# Testing Skill

## Overview
Test-driven development skill that generates and validates unit tests for code.

## Triggers
- When new code is written or existing code is modified
- When test coverage is below threshold

## Inputs
- `source_path`: Path to the source file to test
- `framework`: Testing framework to use (pytest, unittest, jest)
- `coverage_target`: Minimum coverage percentage (default: 80)

## Steps
1. Analyze the source file to identify testable functions and classes
2. Generate test cases for each public interface
3. Include edge cases and error conditions
4. Run tests and verify they pass
5. Report coverage metrics

## Outputs
- Test file with comprehensive test cases
- Coverage report
- List of untested code paths

## Constraints
- Tests must be deterministic
- Tests must not depend on external services
- Each test must be independent
