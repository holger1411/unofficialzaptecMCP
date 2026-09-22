# Security Policy

## Reporting a vulnerability

Please report security issues through GitHub's **Private Vulnerability
Reporting** on this repository, not as public issues. You will get a reply
within a few days.

## Scope and design notes

- Credentials are read only from environment variables or a local `.env`
  file, which is git-ignored. They are never written to disk by the server.
- All logs go to stderr through a redactor that scrubs the password, bearer
  tokens, UUIDs and device serials.
- The server calls only documented endpoints of the Zaptec cloud API and
  never listens on a network port; it speaks MCP over stdio only.
- Three tools change the state of your charging installation. Review the
  permission prompts of your MCP client before approving them.
