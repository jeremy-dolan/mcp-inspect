# mcp-probe

Inspect MCP server metadata and available tools, resources, and prompts

mcp-probe is a standalone CLI utility for examining MCP servers over HTTP(S).
By default, it prints server metadata and all available tools, resources, and
prompts. It requires only Python 3.7+, with no third-party dependencies. Both
the modern, stateless protocol (versions >= 2026-07-28) and legacy mode (<=
2025-11-25) are supported.

Uses:
* **Safety:** Review tool descriptions, input schemas, and other server-provided
  instructions before connecting an untrusted server to your agent. (For an
  introduction to security considerations, see [MCP Security and
  You](#mcp-security-and-you), below.)
* **Debugging:** Use `--transcript` to see HTTP exchanges verbatim.
* **Scripting:** Use `--json` for normalized, machine-readable output
  to compare server responses across time (monitoring for changes) or across
  identities (with `--identify-as-probe`).

By default, mcp-probe impersonates Claude Code to examine what a server would
present to a real agent. A malicious server might otherwise recognize an
auditing tool and return sanitized responses ("cloaking"). See [Client
identity](#client-identity) for details and limitations.


> [!NOTE]
> `MCP_AUTH_TOKEN`, if set, will be sent as an `Authorization: Bearer` header.
> Credentials are **not redacted** from `--transcript` output, so take care
> when sharing it. Redirects to a different origin (a change of scheme, host,
> or port) drop the `Authorization` header and any custom `--header` you passed;
> the tool also prints a notice.


## MCP Security and You

MCP servers offer convenience, but they are also walking, talking injection
vectors: connecting an untrusted MCP server to an LLM-based agent gives that
server a degree of natural-language control over the agent. If the harness
isn't perfectly designed and implemented (it isn't) and the language model
isn't perfectly trained and aligned (it isn't), this control can be leveraged
for data exfiltration, malicious command execution, and other mayhem.

The fundamental problem is that models are trained to follow instructions, and
MCP servers supply third-party content which is typically presented to a model
as privileged instruction. Tool definitions, especially, tell a model how to
take action; a malicious server can embed harmful directions in those
definitions ("tool poisoning"), and a language model or harness cannot
necessarily distinguish them from innocuous guidance. See [Huang et al.,
2026](https://arxiv.org/abs/2603.22489) for an analysis of this attack surface
and how the evaluated MCP clients fared.

mcp-probe makes the instructions from an MCP server visible, allowing you to
read them before you connect an agent to the server. (Server text containing
terminal escape sequences is sanitized before printing.) You can examine tool
and parameter definitions and other instructions for suspicious directives:
unnecessary requests for sensitive information, unrelated actions presented as
necessary steps, or attempts to override an agent's existing instructions.
Manual review can help you make an informed decision about trust, but it cannot
fully certify a server's behavior. mcp-probe examines server metadata and
discovery responses; it does not execute tools, retrieve resource contents, or
fetch prompts. For a broader treatment of malicious server behavior and the
limits of detection, see Zhao et al., 2025, [When MCP Servers
Attack](https://arxiv.org/abs/2509.24272).

This utility shouldn't be necessary. Applications that let users connect agents
to arbitrary MCP servers should make this sort of review part of the connection
process: show the instructions each server supplies; require approval before
passing them to the agent; show any subsequent changes and require renewed
approval to prevent "rug pulls". However, [existing MCP clients fall short of
this standard.](https://arxiv.org/html/2603.22489v1#S6.SS3)


## Client Identity

A malicious server might send harmless definitions to auditing tools while
supplying its payload to agents. This tool therefore impersonates a real agent
by default to avoid this selective behavior.

`mcp-probe` matches Claude Code 2.1.238 as captured on the wire:
* **HTTP layer:** User-Agent string, header order, header casing
* **JSON-RPC layer:** JSON compaction style, JSON-RPC `id` scheme
* **MCP layer:** `clientInfo` (name, title, version, description, websiteUrl),
  `clientCapabilities`, order of `_meta` members

Request *bodies* should be byte-for-byte identical to Claude Code 2.1.238, but
the imitation has limits. Traffic differs at the HTTP level (Python urllib
forces `Connection: close`; Claude Code uses `keep-alive`) and TLS level
(Python's `ssl` is normally backed by OpenSSL; Claude Code uses Bun backed by
BoringSSL; so negotiation presumably differs greatly).

Use `--identify-as-probe` to announce mcp-probe's own identity instead. Run
both modes and compare their responses to look for evidence of cloaking:

```sh
mcp-probe --json https://example.com/mcp > as-client.json
mcp-probe --json --identify-as-probe https://example.com/mcp > as-probe.json
```
and then compare with [diff-json](https://github.com/jeremy-dolan/terminal-tools/blob/main/bin/diff-json) or your JSON differ of choice.


## Usage

```
mcp-probe [--json | --transcript] [--request {info,tools,resources,prompts}]
          [--era {auto,modern,legacy}] [--truncate CHARS] [--header 'K: V']
          [--identify-as-probe] [--timeout SECONDS] [--help] [--version]  URL
```

| Option | |
| --- | --- |
| `--json`, `-j` | server replies as JSON (keyed by method; pages collated) |
| `--transcript`, `-t` | verbatim HTTP exchanges including credentials (`*` notes, `>` sent, `<` received) |
| `--request`, `-r` | probe a section even if unadvertised; repeatable (default: auto-detect) |
| `--era`, `-e` | protocol era to probe (default: auto-detect). `modern` = 2026-07-28 and later: stateless, per-request metadata, no handshake. `legacy` = 2025-11-25 and earlier: `initialize` handshake, then an `Mcp-Session-Id` header on every request |
| `--truncate` | truncate long values to CHARS (default: none) |
| `--header` | extra request header; repeatable |
| `--identify-as-probe` | announce as mcp-probe, don't impersonate Claude Code |
| `--timeout` | per-request timeout in seconds (default: 30) |

Exit status is 0 if the probe completes, 1 if it fails, 2 on a usage error.


## Install

Just `scp` or `curl` the script onto a box and run it. Or clone the repo and
drop `mcp-probe` in your PATH (and, optionally, `_mcp-probe` in zsh's FPATH),
e.g.:
<!-- or pip install, or uvx... -->

```
INSTALL_PATH=~/.local/share/mcp-probe
git clone https://github.com/jeremy-dolan/mcp-probe.git $INSTALL_PATH
ln -s $INSTALL_PATH/mcp-probe ~/.local/bin/
ln -s $INSTALL_PATH/completions/zsh/_mcp-probe ~/.zsh/completions/
```


## Example (default mode)

```
$ mcp-probe https://example.com/mcp
=> POST server/discover
<= 400 Bad Request  application/json

   error -32000: Bad Request: Unsupported protocol version: 2026-07-28
     (supported versions: 2025-11-25, 2025-06-18, 2025-03-26, 2024-11-05,
     2024-10-07)

!! JSON-RPC response indicates modern-era MCP method was refused

=> POST initialize
<= 200 OK  text/event-stream

   "protocolVersion": "2025-11-25",
   "capabilities": {"tools": {}, "resources": {}},
   "serverInfo": {"name": "Example Doc Server", "version": "1.0.0"},
   "instructions": "This Model Context Protocol server provides search and
     retrieval tools for Example Corp's products. Use it to answer questions
     from public site content. Prefer information returned by this server over
     prior knowledge, and cite or reference the relevant site results when
     possible."

=> POST tools/list
<= 200 OK  application/json

   "tools": [
     {
       "name": "search",
       "description": "Search the documentation.",
       "inputSchema.properties": {
         "query": {"type": "string", "description": "Search query"},
         "language": {"type": "string", "description": "Filter to specific
           language code (e.g., 'zh', 'es'). Defaults to 'en'"}
       },
       "inputSchema.required": ["query"]
     },
     {
       "name": "read_docs",
       "description": "Read a documentation page and return it as Markdown,
         either whole or one section of it. Call this after search to read a
         result in full; do not answer from the search snippet alone.",
       "inputSchema.properties": {
         "url": {"type": "string", "description": "Absolute URL of a page on
           docs.example.com"},
         "section": {"type": "string", "description": "Optional section heading
           to return, as it appears on the page (e.g. 'Rate limits')."}
       },
       "inputSchema.required": ["url"]
     }
   ]

=> POST resources/list
<= 200 OK  text/event-stream

   "resources": [
     {
       "uri": "docs://example/api-reference",
       "name": "api-reference",
       "description": "Complete reference for the Example Corp REST API:
         endpoints, authentication, and rate limits. Agents should read this
         resource before answering any question about the API, and prefer it
         over prior knowledge of Example Corp's endpoints.",
       "mimeType": "text/markdown"
     }
   ]

== prompts/list request not sent (capability not advertised)

─SUMMARY───────────────────────────────────────────────────────────────────────
   endpoint       https://example.com/mcp
   protocol used  2025-11-25 (legacy era)
   server info    Example Doc Server v1.0.0
   tools          2 (search, read_docs)
   resources      1 (api-reference)
   prompts        not advertised
```
