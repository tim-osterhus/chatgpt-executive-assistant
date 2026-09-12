# Phone access, dictation, and Live Voice

Agent guide for optional setup. Check the current official instructions before walking the user through menus. Explain one step at a time for beginners.

## Phone access

The phone connects to the assistant running on the user's computer. Use the same executive-assistant conversation after pairing.

Current documented path, checked 2026-09-11:

1. Confirm the latest desktop and mobile apps are signed into the intended account and workspace.
2. On the computer, open **Settings → Connections**.
3. Under **Control this Mac or PC**, choose **Set up** or **Add**.
4. Have the user complete the access and verification prompts.
5. Have the user scan the displayed QR code with their phone.
6. Complete pairing in the mobile app using the same account and workspace.
7. Open **Remote** on the phone and select the computer.
8. Open the existing executive-assistant conversation.

Keep the host awake, online, signed in, and running the app. If the chosen workflow needs foreground computer control, check its platform-specific session requirements.

If the Remote setting is absent, check the app version and current feature availability. Offer an update, help checking availability, or deferral. Record Remote as blocked or deferred and continue ordinary assistant use. Do not restart completed core setup.

Verify phone access with a small read request against an already connected project. Check the actual returned result. Record pairing and any computer-control verification separately.

Sources: [Remote connections](https://learn.chatgpt.com/docs/remote-connections), [Remote overview](https://learn.chatgpt.com/docs/remote), and [Computer Use](https://learn.chatgpt.com/docs/computer-use).

## Dictation

Dictation turns speech into an editable message. It does not start a live conversation.

For a first-time user, point out the microphone control in or near the message box when the current UI exposes it. Identify its exact visible position before describing that position. Do not infer a button location from another platform.

The documented desktop shortcut is **Ctrl+Shift+D** while the message composer is visible. The user can speak, review the transcription, and send it. If a visible microphone button cannot be verified, give this shortcut instead of guessing.

Source: [OpenAI's dictation instructions](https://learn.chatgpt.com/docs/prompting#use-voice-dictation).

## Live Voice

When available, the documented controls are **Start voice chat** in an existing task and **Start new voice chat** for a new task. Prefer the existing assistant task. First use may request microphone access and a voice selection.

Check the controls on the user's actual surface, including mobile Remote. Do not promise that a control available on desktop appears in the same place on mobile.

Offer “Try Live Voice,” “Use dictation,” or “Keep typing.” Voice is optional and does not block core setup.

Keep the initial model choice simple. Use the user's available model and preferences. Suggest a faster voice-facing task or separate manager only if observed latency or workload justifies it and the user wants one.

Source: [ChatGPT Voice](https://learn.chatgpt.com/docs/features/voice).
