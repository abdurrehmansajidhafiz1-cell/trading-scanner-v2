# Trading System Permanent Development Rules

This file defines the mandatory development guidelines and constraints for the Trading Scanner project. The AI assistant must strictly follow these rules during all interactions, code modifications, bug fixes, refactorings, optimizations, and feature additions.

---

### Core Directive (Overriding Rule)
> **CRITICAL**: Do NOT fundamentally change the existing trading logic, strategy rules, or project architecture without explicit user approval.

---

### Development Rules

#### 1. Communication Language & Formatting
- All communication, explanations, suggestions, analysis, and reports must be in **Roman Urdu**.
- All technical terms, Python code, file names, function names, variable names, CLI commands, and error messages must remain in their original **English** format.
- Do NOT output Urdu script (Arabic script), Hindi script, or pure English prose unless explicitly requested by the user.

#### 2. Preserve Existing Functionality
- Preserve all existing working functionality.
- Never modify unrelated files, functions, workflows, or logic unnecessarily.

#### 3. Analysis First
- Before implementing any significant change, analyze the existing implementation thoroughly and explain where and why the change is required in Roman Urdu.

#### 4. Implementation Plan First
- For major changes or architectural modifications, create a detailed implementation plan first.
- Stop and obtain explicit user approval before starting implementation.

#### 5. Minimal Code Changes
- Modify ONLY the required files and specific code blocks needed for the approved task.
- Avoid unrelated refactoring, cosmetic code reformatting, or unnecessary cleanup.

#### 6. Dependency Management
- Do not add any new Python packages, external services, or third-party dependencies without explaining why it is needed and its potential impact on the existing system to the user first.

#### 7. Secrets & Credential Protection
- Never hardcode, expose, print, log, commit, or push API keys, passwords, tokens, SMTP credentials, or any confidential secrets to GitHub or console output. Always use environment variables or GitHub Secrets.

#### 8. Binance & Financial Actions Safety
- Never perform live trading, order placement, funds withdrawal, or any financial transaction.
- Market-data analysis and backtesting must be strictly isolated from live execution.

#### 9. GitHub Repository Protection
- Do not execute `git push`, branch merges, or automated deployments to the GitHub repository without explicit user approval.

#### 10. Automated Testing Requirement
- Run relevant unit/offline tests (`test_offline.py`) after every code modification to prevent regressions.
- If appropriate tests do not exist for a new feature, inform the user and suggest suitable test coverage before completing the task.

#### 11. Strategy Backtesting
- Whenever modifications are made to trading strategy parameters or signal logic, execute a backtest against historical data and provide a detailed comparison between old and new behavior.

#### 12. Git Diff Verification & Summary
- After implementing changes, provide a clear summary of modified files and key code changes.
- Verify changes using `git diff` to ensure only expected modifications were made.

#### 13. Transparent Error Reporting
- Never hide, swallow, or silently mask errors (whether in tests, backtests, GitHub Actions, APIs, or email systems).
- Always identify the exact root cause and explain it clearly to the user in Roman Urdu.

#### 14. No Unverified Assumptions
- If requirements are underspecified or existing system behavior is ambiguous, do NOT make arbitrary assumptions. Ask the user for clarification first.

#### 15. Empirical Verification
- Never declare a task complete without empirical runtime verification (running tests, build checks, or script executions) proving that the implementation works correctly.

#### 16. Documentation Maintenance
- Suggest updates to relevant documentation (`DEPLOYMENT_GUIDE.md`, etc.) whenever major architecture, workflow, or system behavior changes occur.

#### 17. Final Completion Report Structure
At the end of every completed task, provide a final report in Roman Urdu detailing:
1. **Kya change kiya gaya** (What changes were implemented)
2. **Kaun si files change hui** (Which files were modified)
3. **Kya tests run hue** (Which tests were executed)
4. **Kya backtest run hua** (Whether backtesting was performed)
5. **Kya results aaye** (Test & backtest verification results)
6. **Risks ya remaining issues** (Any potential risks or open items)
