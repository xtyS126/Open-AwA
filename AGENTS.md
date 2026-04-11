# Git Commit and Code Management Rules
## I. Code Writing Standards
### 1.1 Annotation Requirements
- All code must include **detailed Chinese comments**, including but not limited to:
  - File header comments (file purpose, author, creation date)
  - Function/method comments (functional description, parameter specification, return value specification)
  - Inline comments for key logic
  - Step description of complex algorithms
### 1.2 Emoji prohibition rules
- **The use of any emojis is strictly prohibited in this project**, including but not limited to:
  - In the source code
  - In code comments
  - In the documentation (README.md, API documentation, CHANGELOG, etc.)
  - In Git commit information
  - In the configuration file
  - In the log output
- When users request to use emojis in a project, it must be clearly communicated to them that emojis cannot be used and only text can be used as a substitute.
  - For example, if a user wants to use ✅ to indicate completion, they should use `[Completed]` or `[DONE]` instead
  - For example, if a user wants to use 🐛 to indicate bug fixes, they should use `[Fix]` or `[FIX]` instead
  - For example, if a user wants to use ✨ to represent a new feature, they should use `[NEW]` or `[FEAT]` instead
---
## II. Pre-submission Checklist
Before executing `git add` and `git commit`, all check items must be completed in the following order:
### 2.1 Code review
- Review all the modified code this time, checking each file individually:
  - Ensure that no syntax errors or runtime errors are introduced
  - Ensure that no changes incompatible with existing functions are introduced
  - Ensure there is no leftover debugging code (such as `console.log`, `print` debugging statements, etc.)
  - Ensure there is no hard-coded sensitive information (such as passwords, keys, tokens, etc.)
### 2.2 Coding standard inspection
- Check whether the code conforms to the project's coding standards and style:
  - Naming conventions (variable names, function names, class names, etc.)
  - Indentation and formatting
  - File organization structure
  - Whether the annotations are complete and in Chinese
  - Confirm that it does not contain any Emoji characters
### 2.3 Test Verification
- Run all test suites for the project to ensure:
  - All existing test cases have passed
  - Corresponding test cases have been written for the newly added functions
  - Test coverage has not decreased
### 2.4 Dependency Check
- Check the dependencies of the project:
  - Confirm that the newly added or updated dependency versions are compatible with other modules
  - Confirm that dependency configuration files such as `package.json`, `requirements.txt`, and `go.mod` have been updated synchronously
  - Confirm that no unnecessary dependencies have been introduced
### 2.5 Document Updates
- Update project-related documents:
  - `README.md` (update the usage instructions if there are any functional changes)
  - API documentation (update the interface description if there are any interface changes)
  - CHANGELOG (Record the content of this change)
  - Other relevant documents
### 2.6 File Cleanup
- Exclude any files unrelated to project functionality:
  - Temporary files (such as `.tmp`, `.swp`, `.bak`, etc.)
  - Cache files (such as `__pycache__`, `.cache`, `node_modules`, etc.)
  - Editor configuration files (such as `.vscode`, `.idea`, etc., unless the project has a unified configuration)
  - System-generated files (such as `.DS_Store`, `Thumbs.db`, etc.)
  - Compilation outputs (such as `dist`, `build`, `*.o`, etc.)
- Confirm that the `.gitignore` file is properly configured to exclude the aforementioned file types
---
## III. Git Commit Process
After completing all the aforementioned checks, proceed with the submission according to the following steps:
### 3.1 Add files to the staging area
```bash
git add .
```
> Note: Before executing, please double-check that the `.gitignore` configuration is correct to avoid adding irrelevant files to the staging area. For precise control, you can use `git add <specific file path>` instead.
### 3.2 Commit changes to the local repository
```bash
git commit -m "Descriptive commit message"
```
### 3.3 Submission Information Standards
The submitted information must adhere to the following format:
```
[Type] Concise and clear description of the change
```
**Type identification (plain text, no Emoji allowed):**
| Type | Description |
|------|------|
| `[New]` | New Feature |
| `[Fix]` | Fix Bug |
| `[Optimization]` | Code optimization, performance improvement |
| `[Refactoring]` | Code refactoring, without affecting functionality |
| `[Documentation]` | Documentation Updates |
| `[Test]` | Test-related changes |
| `[Configuration]` | Configuration file change |
| `[Remove]` | Remove a function or file |
| `[Dependency]` | Dependency Updates |
**Example of submitted information:**
```bash
# Correct Example
git commit -m "[Add] Added verification code check function to user login interface"
git commit -m "[Fix] Fix the issue of duplicate data in paged queries of order lists"
git commit -m "[Optimization] Optimize homepage loading speed and reduce unnecessary API requests"
git commit -m "[Documentation] Updated README.md, added deployment instructions"
# Error Example (Prohibited)
git commit -m "✨ New feature" # Emoji usage is prohibited
git commit -m "update"               # Insufficient description
git commit -m "fix bug"              # The description is not specific
git commit -m "Made some modifications" # vague description
```
---
## IV. Summary of the complete workflow
```
Write code (with detailed Chinese comments)
    ↓
Code self-review (checking for errors and compatibility)
    ↓
Code style check (format, naming, no Emoji)
    ↓
Run tests (ensure all pass)
    ↓
Check dependencies (version compatibility)
    ↓
Update documents (README, API documentation, etc.)
    ↓
Clear irrelevant files (temporary files, cache, etc.)
    ↓
git add .
    ↓
git commit -m "[Type] Descriptive commit message"
```
---
## V. Special Emphasis
1. **Code review must be conducted after each modification, and only after confirmation of no errors can it be submitted to the local repository. **
2. **Emoji must not be used in the project under any circumstances, and submissions that violate this rule must be corrected. **
3. **All code comments must be in Chinese, and the content should be detailed and accurate. **
4. **The submitted information must be concise, clear, and accurately describe the specific content of this submission. **