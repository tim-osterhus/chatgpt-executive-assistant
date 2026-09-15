# Phone access, dictation, and Live Voice

Agent guide for optional, highly recommended setup. Offer this after the first useful result, as directed by [SETUP.md](../SETUP.md). Check current official instructions before walking the user through menus. Explain one step at a time for beginners.

## The intended experience

Phone → Remote → the existing Executive Assistant task → connected projects and existing tasks → verified results back in the same conversation.

The user talks to their orchestration manager using ChatGPT Voice, powered by GPT-Live. That task uses this workspace's index and project routes to coordinate work. It keeps the same context and responsibilities when the user switches between voice and typing.

Reuse the existing Executive Assistant task. Record its exact identifier and host in `local/index.md` when available, so the user can find it again. Pairing a phone does not require a separate voice manager or new tasks inside every project.

## Phone access

The phone connects to the assistant running on the user's computer. Use the same executive-assistant conversation after pairing.

Current documented path, checked 2026-09-15:

1. Confirm the latest desktop and mobile apps are signed into the intended account and workspace.
2. On the computer, open **Settings → Connections**.
3. Under **Control this Mac or PC**, choose **Set up** or **Add**.
4. Have the user complete the access and verification prompts.
5. Have the user scan the displayed QR code with their phone.
6. Complete pairing in the mobile app using the same account and workspace.
7. Open **Remote** on the phone and select the computer.
8. Select the **Executive Assistant** project and open its existing orchestration task. Confirm its identity against the host task.

Keep the host awake, online, signed in, and running the app. Review **Settings → Connections** for the host's keep-awake option where available. If the chosen workflow needs foreground computer control, check its platform-specific session requirements.

If the Remote setting is absent, check the app version and current feature availability. Offer an update, help checking availability, or deferral. Record Remote as blocked or deferred and continue ordinary assistant use. Do not restart completed core setup.

Verify phone access with a small read request against an already connected project. Check the actual returned result. Record pairing and any computer-control verification separately.

Sources: [Remote connections](https://learn.chatgpt.com/docs/remote-connections), [Remote overview](https://learn.chatgpt.com/docs/remote), and [Computer Use](https://learn.chatgpt.com/docs/computer-use).

## Dictation

Dictation turns speech into an editable message. It does not start a live conversation.

For a first-time user, point out the microphone control in or near the message box when the current UI exposes it. Identify its exact visible position before describing that position. Do not infer a button location from another platform.

The documented desktop shortcut is **Ctrl+Shift+D** while the message composer is visible. The user can speak, review the transcription, and send it. If a visible microphone button cannot be verified, give this shortcut instead of guessing.

Source: [OpenAI's dictation instructions](https://learn.chatgpt.com/docs/prompting#use-voice-dictation).

## Live Voice

Official documentation explicitly supports GPT-Live through Remote on iOS. Remote itself also supports Android. Verify Live Voice availability on the user's phone before promising that part of the flow.

When available, the documented controls are **Start voice chat** in an existing task and **Start new voice chat** for a new task. Prefer the existing assistant task. First use may request microphone access and a voice selection.

Check the controls on the user's actual surface, including mobile Remote. Do not promise that a control available on desktop appears in the same place on mobile.

Offer “Try Live Voice,” “Use dictation,” or “Keep typing.” Voice is optional and does not block core setup.

Keep the initial model choice simple. Use the user's available model and preferences. Suggest a faster voice-facing task or separate manager only if observed latency or workload justifies it and the user wants one.

Source: [ChatGPT Voice](https://learn.chatgpt.com/docs/features/voice).

## Verify the whole route

After pairing, guide the user from their phone through these steps:

1. Open the existing Executive Assistant task through Remote.
2. Start Live Voice using the control available in that task, then complete any microphone prompt.
3. Offer a spoken request such as “Check my connected project and tell me what needs my attention.”
4. Retrieve current evidence from that project and explain the result in the same conversation.
5. If task delegation is connected, offer “Ask the existing project task for a brief status update,” or “Skip the delegation test.”
6. For the selected delegation test, send the bounded request through the verified route and retrieve the actual reply.

Record Remote access, Live Voice, and delegated execution as separate observations, with dates and evidence. A successful voice conversation does not prove that project delegation works. If no delegation route is connected yet, record that test as deferred.

If Live Voice is unavailable, verify Remote with a typed or dictated request and record voice as deferred. Show the user how to return to this same task next time. Keep completed core setup intact.
