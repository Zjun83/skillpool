# Debugging Skill

## Overview
Systematic debugging skill that helps diagnose and fix errors in code.

## Triggers
- When a test fails or a build breaks
- When unexpected behavior is observed

## Inputs
- `error_message`: The error message or stack trace
- `source_path`: Path to the relevant source file
- `context_lines`: Optional number of context lines to show

## Steps
1. Parse the error message to identify the root cause type
2. Locate the relevant source file and line numbers
3. Analyze the code path that led to the error
4. Identify potential fixes and rank by likelihood
5. Suggest the most probable fix with explanation

## Outputs
- Root cause analysis
- Suggested fix with code changes
- Prevention recommendations

## Constraints
- Must not make assumptions without evidence
- Must consider all possible causes before suggesting a fix
- Must verify the fix doesn't introduce new issues
