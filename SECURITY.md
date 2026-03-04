# Security Policy

## Reporting a Vulnerability

To report vulnerabilities, you can privately report a potential security issue
via the GitHub security vulnerabilities feature. This can be done here:
https://github.com/Indhar01/MemoGraph/security/advisories


Please do **not** open a public issue about a potential security vulnerability.

You can find more details on the security vulnerability feature in the GitHub
documentation here:

https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability

## Security Best Practices

When using MemoGraph, please consider the following security best practices:

### API Keys and Credentials

- **Never commit API keys** to version control
- Use environment variables for sensitive credentials
- Rotate API keys regularly
- Use separate API keys for development and production

### Data Privacy

- Be mindful of sensitive information in your memory vault
- Consider encrypting vault directories containing sensitive data
- Review what data you're storing in your memories

### Dependencies

- Keep MemoGraph and its dependencies up to date
- Review security advisories for dependencies
- Use virtual environments to isolate dependencies

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.0.x   | :white_check_mark: |

## Security Updates

Security updates will be released as patch versions and announced in the [CHANGELOG](CHANGELOG.md).