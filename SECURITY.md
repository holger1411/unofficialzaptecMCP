# Security Policy

## Reporting a vulnerability

Please report security issues through GitHub's **Private Vulnerability
Reporting** on this repository, not as public issues. You will get a reply
within a few days.

## Scope and design notes

- Credentials are read only from environment variables or an env file
  (`ZAPTEC_ENV_FILE`, or `./.env` if that is unset). The repository git-ignores
  `.env`. The server never writes credentials to disk.
- All logs go to stderr through a redactor that scrubs the password, bearer
  tokens, UUIDs and device serials. Exception tracebacks pass through the
  same redactor.
- The server calls only documented endpoints of the Zaptec cloud API and
  never listens on a network port; it speaks MCP over stdio only.

## Credential storage

- Credentials placed in the `env` block of `claude_desktop_config.json` are
  stored in plain text. Anyone who can read that file can read your password.
- Better: keep them in a separate env file, run `chmod 600` on it, and point
  `ZAPTEC_ENV_FILE` at it. The server logs a warning if that file is readable
  by group or others.
- The Claude Desktop extension bundle (`manifest.json`) marks the password as
  sensitive, so Claude Desktop stores it in the operating system keychain.
- Never commit `.env` or any file that holds credentials.

## Input validation and network rules

- Charger and installation ids must be canonical UUIDs. Anything else is
  rejected before a URL is built. This stops an id such as
  `../chargers/x/state` from reaching a different endpoint.
- `ZAPTEC_API_BASE_URL` must use `https://`. Plain `http://` is accepted only
  for `localhost`, `127.0.0.1` and `::1`, so credentials cannot be sent over
  an unencrypted connection to a remote host.

## Untrusted data from the API

Charger names, installation names and addresses come from the Zaptec API and
are returned to the model as text. Whoever can edit those fields in a Zaptec
account can put arbitrary text there, including text that looks like
instructions. Treat it as untrusted data. Review what your assistant does
with it, and keep the permission prompt for state-changing tools switched on.

## State-changing tools

`zaptec_pause_charging`, `zaptec_resume_charging` and
`zaptec_set_available_current` change the state of your installation. The
server marks them with MCP tool annotations (`readOnlyHint: false`;
`destructiveHint: true` for `zaptec_set_available_current`). The three
read-only tools are marked `readOnlyHint: true`. A client can use these hints
to ask for confirmation. Review the permission prompts of your MCP client
before approving them. Setting the available current to `0` stops charging
for the whole installation.
