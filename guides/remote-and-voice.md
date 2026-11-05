# Phone access, dictation, and Live Voice

Agent guide for optional phone access. It does not gate core setup or outbound calling. Check current official instructions before walking the user through menus, and explain one step at a time for beginners.

## Phone access

The ChatGPT mobile app can connect to a computer running the ChatGPT desktop app. After pairing, the user can open an existing project task from the phone. Use the task and model the user already chose; do not create a dedicated Voice task as a requirement.

Current setup path, checked 2026-11-05:

1. Confirm the desktop and mobile apps are signed in to the intended account and workspace.
2. On the computer, open **Settings → Connections → Control this Mac or PC**, then select **Set up** or **Add**.
3. Complete the access and verification prompts, then scan the QR code with the phone.
4. Finish pairing in the mobile app using the same account and workspace.
5. Open **Codex** on iOS, or **Remote** if the app still uses that label. Select the connected computer and the **Executive Assistant** project, then open the existing task.

Keep the host awake, online, signed in, and running the app. If a setting is absent, check current app versions and account or workspace availability. Offer deferral and continue ordinary assistant use. Verify access with a small read request against a connected source and record the actual result.

Source: [Remote connections](https://learn.chatgpt.com/docs/remote-connections).

## Dictation

Dictation turns speech into editable message text. It is not a live conversation. Point out a microphone control only when its location is visible in the current UI. If dictation is unavailable, offer typing or the operating system's dictation feature.

Source: [Voice dictation](https://learn.chatgpt.com/docs/prompting#use-voice-dictation).

## Live Voice

ChatGPT Voice is an optional live conversation in the ChatGPT desktop app. When available, it can run in an existing Codex task and uses that task's conversation and selected model. Voice on mobile is available through Codex on iOS after pairing a computer; availability depends on rollout, plan, and workspace settings. Check the current controls and official documentation before promising availability.

Start voice in the existing **Executive Assistant** task when the user chooses to use it. Do not create a separate Voice task or change model settings just to use voice or outbound calls. If voice is unavailable, keep using typing or dictation. Live Voice and outbound calls are separate workflows: Live Voice is the user's ongoing conversation with ChatGPT; outbound calling uses a separate voice agent that receives a prepared briefing and returns a saved receipt.

Source: [ChatGPT Voice](https://learn.chatgpt.com/docs/features/voice).

## Verify phone access

After pairing, have the user open the known project task through the mobile app and make a small request against an already connected source. Check the actual returned result. Record Remote access and Live Voice separately; a successful voice conversation does not prove project access or task delegation.

If Live Voice is unavailable, verify phone access with a typed request and record Voice as deferred. Keep completed core setup intact.
