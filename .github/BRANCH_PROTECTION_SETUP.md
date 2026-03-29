# Branch Protection Setup Guide

This guide explains how to set up branch protection rules for the MemoGraph repository to require code review before merging to `main`.

## Overview

Branch protection rules help maintain code quality by:
- Requiring pull request reviews before merging
- Enforcing CI checks to pass
- Preventing direct pushes to protected branches
- Ensuring code quality standards

## Prerequisites

- ✅ CODEOWNERS file created (`.github/CODEOWNERS`)
- ✅ CI workflows configured (`.github/workflows/ci.yml`)
- ✅ Repository admin access on GitHub

## Step-by-Step Setup

### Step 1: Access Branch Protection Settings

1. Go to your GitHub repository: `https://github.com/Indhar01/MemoGraph`
2. Click the **Settings** tab (top navigation)
3. In the left sidebar, click **Branches**
4. Click **Add branch protection rule** (or **Add rule**)

### Step 2: Configure Branch Pattern

In the **Branch name pattern** field, enter:
```
main
```

This applies the rules to your `main` branch.

### Step 3: Require Pull Request Reviews

Check the following options:

#### ✅ Require a pull request before merging
- **Required approvals**: Set to `1` (or higher for more strict review)
- ✅ **Dismiss stale pull request approvals when new commits are pushed**
  - Ensures reviewers re-review after changes
- ✅ **Require review from Code Owners**
  - Automatically enforces review from people listed in CODEOWNERS
- ✅ **Require approval of the most recent reviewable push**
  - Ensures the latest version is approved

### Step 4: Require Status Checks (CI)

#### ✅ Require status checks to pass before merging

Select these CI checks from your workflows:
- `lint` - Code linting with ruff
- `test` - Test suite across OS/Python versions
- `test-enhanced` - Enhanced module tests
- `integration` - Integration tests
- `quality-gates` - Final quality validation

#### ✅ Require branches to be up to date before merging
- Ensures branch has latest main changes before merging

### Step 5: Additional Protections (Recommended)

#### ✅ Require conversation resolution before merging
- All PR comments must be resolved

#### ✅ Require signed commits (Optional)
- Enhanced security through commit signing

#### ✅ Require linear history (Optional)
- Prevents merge commits, enforces rebase/squash

#### ✅ Include administrators
- Apply rules to repository admins too (recommended for consistency)

#### ⬜ Lock branch (Not Recommended)
- Only enable if you want to make the branch read-only

#### ⬜ Do not allow bypassing the above settings (Optional)
- More strict enforcement

### Step 6: Restrict Push Access (Optional)

If you want to limit who can push to main:

#### ✅ Restrict who can push to matching branches
- Add specific users or teams who can push

### Step 7: Rules Applied to Everyone (Recommended)

#### ✅ Allow force pushes - Everyone
- Generally **leave unchecked** for main branch

#### ✅ Allow deletions
- Generally **leave unchecked** for main branch

### Step 8: Save the Rule

Click **Create** or **Save changes** at the bottom.

## Verification

After setup, test the protection:

### Test 1: Try Direct Push (Should Fail)
```bash
git checkout main
git pull origin main
echo "test" >> README.md
git add README.md
git commit -m "test: direct push"
git push origin main
```

**Expected**: ❌ Push rejected with message about branch protection

### Test 2: Create Pull Request (Should Work)
```bash
git checkout dev
echo "test" >> README.md
git add README.md
git commit -m "test: PR workflow"
git push origin dev
```

Then on GitHub:
1. Create Pull Request from `dev` to `main`
2. Wait for CI checks to complete ⏳
3. Request review or self-review (if allowed)
4. After approval ✅ and CI passes ✅ → Merge button enabled

## Recommended Configuration Summary

```yaml
Branch: main
Protection Rules:
  ✅ Require pull request before merging
     - Required approving reviews: 1
     - Dismiss stale reviews: Yes
     - Require review from Code Owners: Yes
     - Require approval of latest push: Yes
  
  ✅ Require status checks to pass
     - Required checks: lint, test, test-enhanced, integration, quality-gates
     - Require branches up to date: Yes
  
  ✅ Require conversation resolution: Yes
  ✅ Include administrators: Yes
  ✅ Require linear history: Yes (Optional)
  
  ❌ Allow force pushes: No
  ❌ Allow deletions: No
```

## Workflow After Setup

### For Contributors (Including You):

1. **Always work on feature branches**
   ```bash
   git checkout dev
   git pull origin dev
   # Make your changes
   git add .
   git commit -m "feat: your feature"
   git push origin dev
   ```

2. **Create Pull Request**
   - Go to GitHub and create PR from `dev` to `main`
   - Fill in PR description
   - Wait for CI checks

3. **Review and Merge**
   - Review your own code (or get teammate review)
   - Ensure all CI checks pass
   - Click "Merge pull request"

### Emergency Hotfixes

If you need to bypass (only if admin bypass is enabled):
1. Temporarily disable branch protection
2. Make critical fix and push
3. Re-enable branch protection immediately

**Note**: This should be rare and only for emergencies!

## Benefits of This Setup

✅ **Code Quality**: All code is reviewed before merging
✅ **CI Enforcement**: Tests must pass before merge
✅ **Audit Trail**: All changes tracked through PRs
✅ **Collaboration**: CODEOWNERS automatically assigns reviewers
✅ **Safety**: Prevents accidental direct pushes to main
✅ **Best Practices**: Encourages proper Git workflow

## Troubleshooting

### Issue: "Review required" but I'm the only developer
**Solution**: 
- Either allow self-review by not including administrators in rules
- Or temporarily disable "Require review from Code Owners" for personal projects
- Or add a secondary GitHub account as collaborator

### Issue: CI checks not appearing in required checks
**Solution**:
- Push a PR first to trigger CI
- After CI runs once, the check names will appear in settings
- Then you can select them as required

### Issue: Can't merge even after approval
**Solution**:
- Check if all CI checks passed
- Check if conversations are resolved
- Check if branch is up to date with main

## Alternative: GitHub CLI Setup

If you prefer using CLI:

```bash
# Install GitHub CLI if not installed
# Visit: https://cli.github.com/

# Enable branch protection via API
gh api repos/Indhar01/MemoGraph/branches/main/protection \
  --method PUT \
  --field required_pull_request_reviews[required_approving_review_count]=1 \
  --field required_pull_request_reviews[dismiss_stale_reviews]=true \
  --field required_pull_request_reviews[require_code_owner_reviews]=true \
  --field required_status_checks[strict]=true \
  --field required_status_checks[contexts][]=lint \
  --field required_status_checks[contexts][]=test \
  --field required_status_checks[contexts][]=test-enhanced \
  --field required_status_checks[contexts][]=integration \
  --field required_status_checks[contexts][]=quality-gates \
  --field enforce_admins=true \
  --field required_linear_history=true
```

## Resources

- [GitHub Branch Protection Documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [CODEOWNERS Documentation](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)
- [GitHub Actions Status Checks](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/about-status-checks)

## Questions?

If you encounter any issues with branch protection setup, refer to this guide or check GitHub's official documentation.

---

**Setup Date**: 2026-03-29  
**Last Updated**: 2026-03-29  
**Maintained By**: @Indhar01