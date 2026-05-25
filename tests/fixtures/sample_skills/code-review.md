# Code Review Skill

## Overview
Automated code review skill that analyzes pull requests for quality, security, and style issues.

## Triggers
- When a pull request is opened or updated
- When code review is requested

## Inputs
- `pr_url`: URL of the pull request to review
- `focus_areas`: Optional list of areas to focus on (security, performance, style)

## Steps
1. Fetch the PR diff using the provided URL
2. Analyze changed files for common issues
3. Check for security vulnerabilities in modified code
4. Verify test coverage for new code
5. Generate review comments with suggestions

## Outputs
- Review summary with severity-tagged findings
- Inline comments on specific code lines
- Overall quality score (0-100)

## Constraints
- Must not modify any code, only review
- Must complete analysis within 60 seconds
- Must respect .gitignore patterns
