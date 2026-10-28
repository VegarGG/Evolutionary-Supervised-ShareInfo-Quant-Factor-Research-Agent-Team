# Standard MCP clients

These are connection instructions with placeholders, not recorded acceptance.
Use the existing Mac deployment at `http://127.0.0.1:8000/mcp` only after its
readiness checks. The operator supplies a short-lived test credential scoped to
the intended program and role. Never paste credential values into commands,
configuration examples, model/tool arguments or public logs. No QFR provider call
is needed for these transport demonstrations.

## Codex

The installed Codex CLI advertises a standard Streamable HTTP connection and
bearer-token environment reference:

```sh
codex mcp add qfr --url http://127.0.0.1:8000/mcp \
  --bearer-token-env-var QFR_MCP_TOKEN
```

Run registration only in the intended local Codex configuration after checking
for an existing `qfr` entry. Populate the referenced variable privately using the
owner's credential mechanism; the command contains its name, not its value. This
changes client configuration, not QFR job lifetime. The equivalent TOML entry is:

```toml
[mcp_servers.qfr]
url = "http://127.0.0.1:8000/mcp"
bearer_token_env_var = "QFR_MCP_TOKEN"
```

Use the discovered typed tools in the order described by the
[portable intake guide](PORTABLE_INTAKE_GUIDE.md). The actual Mac demonstration
must record the installed client version and negotiated protocol, admit a real
pilot job, save its ID, disconnect, reconnect, poll and request/download its
accepted export. `codex mcp list` alone does not prove tool execution.

For a model-free automated transport demonstration, the inspected Codex binary
also exports the app-server methods `mcpServerStatus/list`,
`mcpServer/tool/call` and `mcpServer/resource/read`. Verify these against the
**Mac's** installed `codex app-server generate-json-schema --experimental` output;
this is a client capability, not a required QFR extension. The tool-call request
requires a server name, actual app-server thread ID, tool name and arguments.
Initialize the app-server with experimental API capability, use an ephemeral
thread without starting a model turn, and invoke only QFR tools. Neither generated
schemas nor this proposed sequence prove that the real Mac Codex gate passed.
If the installed version cannot perform it, report the missing capability rather
than substituting an SDK fixture for Codex or making an unapproved provider call.

## Independent SDK command-line client

The repository also ships an independent, model-free client using the maintained
MCP SDK. Its private `PublicServiceClientConfiguration` file uses the service
**base** URL, not the `/mcp` suffix:

```json
{
  "revision": 1,
  "base_url": "http://127.0.0.1:8000",
  "token_ref": "env:QFR_MCP_TOKEN",
  "timeout_seconds": 15,
  "max_request_bytes": 262144,
  "max_response_bytes": 4194304
}
```

```sh
python -m qfr_mcp.client --client-config /private/client.json list-tools
python -m qfr_mcp.client --client-config /private/client.json \
  call qfr_research_submit /private/submit-arguments.json
python -m qfr_mcp.client --client-config /private/client.json \
  call qfr_research_status /private/status-arguments.json
python -m qfr_mcp.client --client-config /private/client.json \
  read-resource 'job://PROGRAM_UUID/JOB_UUID/0'
```

Arguments are exactly the discovered tool schema: for submission,
`{"program_id":"PROGRAM_UUID","value":{...JobAdmission...}}`; status takes
`program_id` and `job_id`. Fill real IDs and complete validated objects, never the
ellipsis or example identities. Each command connects, negotiates and disconnects.
Repeat a lost submission with the same key and bytes. The job remains in Research
API independently of these processes. Tool errors return a nonzero CLI status;
transport failure is not job failure or completion. No model client is imported
or called by this program.

Read paginated resources until every page with the same whole-document hash is
present. Use authenticated ordinary HTTP for binary chunks and export downloads,
checking original/final SHA256 and size. Do not base64-encode a model package into
a tool call. A large inline request must be refused; a missing source or failed
hash must remain visible.

## Demonstration record

Use separate client runs against the same deployed APIs. Record each client's
connect, typed discovery, submit, disconnect, reconnect, poll and verified export,
including same-key recovery and changed-payload conflict. Include status-request
cancellation, a real server restart, reader/cross-program refusal, absence of admin
tools, unsafe imports, oversized inline data and unsigned/tampered official
evidence. Preserve source hashes and private logs locally. Report full real-pilot
and elapsed-batch evidence separately from small synthetic component tests.
