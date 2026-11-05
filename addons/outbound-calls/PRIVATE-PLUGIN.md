# Optional private calling connector

This opt-in connector exposes the existing calling runner through three MCP tools: `calling_health`, `request_call`, and `get_call_status`. Core setup and local CLI calling do not require it. Each user installs their own private connector. Secure MCP Tunnels do not support distribution through a public plugin directory.

Complete [calling setup](SETUP.md) first. The connector uses that runtime's fixed recipient, credentials, disclosure, and call limit. It accepts a focus and briefing, never a destination number. It does not change Twilio account configuration. The voice agent speaks from the supplied briefing and cannot inspect projects during the call.

## Install separately

On Apple Silicon macOS, from this add-on directory:

```sh
.venv/bin/python -I -B scripts/private_plugin.py install
```

This installs the official `openai/tunnel-client` v0.0.19 archive after checking its pinned SHA256, writes only its executable, and installs pinned MCP dependencies into `.plugin-venv`. It does not alter ordinary `setup.sh` dependencies or enable dialing. Other platforms are not supported by this installer. Review future client updates and their checksums before changing the pin. See the [upstream tunnel-client license](https://github.com/openai/tunnel-client/blob/v0.0.19/LICENSE).

## Create and connect a private tunnel

First confirm that Platform Secure MCP Tunnel and the custom plugin **Tunnel** connection option are available to your account and workspace. If either is unavailable, defer this connector and continue using the core assistant and local calling CLI.

In Platform tunnel settings, create or reuse a tunnel associated with the intended ChatGPT workspace and Platform organization. Creation requires Tunnels Read + Manage. The restricted runtime key and connector operator need Read + Use. Workspace policy must permit custom MCP servers. Follow [OpenAI's Secure MCP Tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) for current permissions and UI.

Configure the actual identifiers locally. Replace both placeholders:

```sh
.venv/bin/python -I -B scripts/private_plugin.py configure \
  --tunnel-id '<created-tunnel-id>' \
  --workspace-id '<verified-workspace-uuid>'
.venv/bin/python -I -B scripts/private_plugin.py store-key
.venv/bin/python -I -B scripts/private_plugin.py connect
.venv/bin/python -I -B scripts/private_plugin.py status
```

`store-key` prompts privately and stores the runtime key in macOS Keychain, service `executive-assistant-calls.openai-tunnel-runtime`, account `private-calling`. Never paste the key into chat, command arguments, source files, or logs. The helper supplies it to the managed runtime through an environment reference. `run-plugin` strips API/access keys before starting MCP. The phone subprocess receives only its explicit environment whitelist and retrieves its own credentials through the existing runner.

The saved workspace ID records the intended association. The helper cannot grant or verify that server-side association. Verify it in Platform.

`connect` uses managed alias/profile `private-calling`. Inspect the private `.state/plugin/status-last.json` and operation logs for actual readiness and active polling. A zero exit status alone does not establish tool connectivity. Stop with `.venv/bin/python -I -B scripts/private_plugin.py stop`.

Only after opting into the private connection, review and grant its plugin consent permissions in your own workspace. In ChatGPT, add a custom MCP server with **Connection: Tunnel**, select the same tunnel, and configure the private inner stdio server with no additional authentication. The authenticated tunnel enforces its permitted organization/workspace context. Do not expose this unauthenticated stdio adapter through public HTTP. Its transport is separate from the voice runtime's temporary media tunnel. [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) are temporary development URLs, with no uptime guarantee.

## Verify before enabling calls

1. Keep the local host awake, online, and the managed tunnel connected. Discover the three tools and invoke `calling_health`. Confirm configuration, recipient last four digits, disclosure, and call limit. Dialing should be disabled. Health does not read credentials or make a call.
2. Only when ready to authorize calls through this private connector, enable the local gate:

   ```sh
   mkdir -p .state/plugin
   chmod 700 .state/plugin
   touch .state/plugin/dial-enabled
   chmod 600 .state/plugin/dial-enabled
   ```

3. Ask for one test call. Supply a new strict lowercase request slug, a short focus, and a current non-empty briefing. A request response of `accepted` means submission, not completion.
4. Retrieve `get_call_status` using that exact request ID. Review its terminal receipt and transcript before recording decisions or follow-up. A partial conversation does not establish a confirmed recap.

Disable new calls by removing `.state/plugin/dial-enabled`. This does not cancel an already running call. Stopping the tunnel also does not stop an already detached phone runner.

## Duplicate and uncertain submissions

The plugin saves an immutable request before launching. Reusing an ID never launches again. Changing its briefing is rejected. Another unresolved request blocks new IDs. On uncertainty, query the original ID and inspect its local evidence. Never delete the journal or redial to resolve an ambiguous submission.

Only a receipt bound to the exact saved request and a terminal carrier status (or a verified failure before dialing) releases admission. The public result excludes the runner’s host evidence-path field.

There is no callback, scheduler, or unattended monitoring service in this connector. The coordinator must retrieve results explicitly. Restart after logout/reboot and operation while the host sleeps have not been verified. Do not promise automatic availability. Offline tests cover submission safety and protocol discovery. Each installation still needs its own health check, authorized call, and exact-ID terminal retrieval.
