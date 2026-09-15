# Phone access, dictation, and Live Voice

Agent guide for optional, highly recommended phone setup. Offer this after the first useful result, as directed by [SETUP.md](../SETUP.md). Check current official instructions before walking the user through menus. Explain one step at a time for beginners.

## The intended experience

Phone → Remote → the dedicated Executive Assistant Voice task. For substantial work, Voice routes to the existing Executive Assistant High orchestration task → existing project managers and Luna Max workers → verified replies through Voice.

Use one dedicated Voice task for every Live Voice session. Keep it in this same local **Executive Assistant** project. Voice uses Astra Light, model `gpt-6-astra` with reasoning `low`. Verify the model and reasoning setting in the runtime catalog. The desktop **Light** label maps to CLI `low`.

Voice handles conversation, clarification, routing, status relay, and quick self-contained work. It may handle a small status lookup, file or note edit, scoped connector action, or quick browser action within existing authorization. Light owns the decision and completion check for those small actions.

Route substantial planning, cross-project coordination, long execution, and substantial browser or computer-control work to the existing High task. High owns central summaries and job files, plus decisions and dispatch for substantial routed work. Existing project managers and Luna Max workers keep their responsibilities.

Record the exact Voice and High task identifiers, hosts, requested models and reasoning, verified models and reasoning, and verification dates in `local/index.md`. The setup coordinator owns the initial role record. Voice sends meaningful summary changes to High and does not create duplicate job ownership.

When the user chooses Voice setup, reuse the matching task or create one in the same workspace folder through a supported task tool. Its initial instructions must identify its Voice role, the verified High task ID and host, this guide, and the small-action boundary. Select Astra Light for that task and verify the result. If creation is still pending, wait for its real task identifier before recording or using it.

The initial instructions must also tell Voice that High owns setup and central records. Voice should not independently restart onboarding while setup is in progress.

## Phone access

The phone connects to the assistant running on the user's computer. Open the recorded Executive Assistant Voice task after pairing.

Current documented path, checked 2026-09-15:

1. Confirm the latest desktop and mobile apps are signed into the intended account and workspace.
2. On the computer, open **Settings → Connections**.
3. Under **Control this Mac or PC**, choose **Set up** or **Add**.
4. Have the user complete the access and verification prompts.
5. Have the user scan the displayed QR code with their phone.
6. Complete pairing in the mobile app using the same account and workspace.
7. Open **Remote** on the phone and select the computer.
8. Select the **Executive Assistant** project. Reuse the existing dedicated Voice task, or create exactly one there if the user selected creation during setup and a supported task tool is available. Confirm its task identifier and host against the recorded role.

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

When available, start Live Voice only in the dedicated Executive Assistant Voice task. The documented controls are **Start voice chat** in an existing task and **Start new voice chat** for a new task. First use may request microphone access and a voice selection. Do not start Live Voice in High or a worker task by default.

Check the controls on the user's actual surface, including mobile Remote. Do not promise that a control available on desktop appears in the same place on mobile.

Tell the user to keep every Live Voice session in the dedicated Voice task. Typed requests and dictation remain usable in either Voice or High. If Live Voice is active in another task, tell them: “Stop the current voice session, open Executive Assistant Voice, and start voice there.” Treat this as workflow guidance. Follow an explicit user override and record it.

Offer “Try Live Voice,” “Use dictation,” or “Keep typing.” Voice is optional and does not block core setup. If Astra Light, the Voice task, or Live Voice is unavailable, record Voice as deferred and keep typed or dictated use available. Do not silently route Live Voice through High.

Source: [ChatGPT Voice](https://learn.chatgpt.com/docs/features/voice).

## Verify the whole route

After pairing, guide the user from their phone through these steps:

1. Open the dedicated Executive Assistant Voice task through Remote.
2. Start Live Voice using the control available in that task, then complete any microphone prompt.
3. Offer a spoken request such as “Check my connected project and tell me what needs my attention.”
4. Let Voice handle a quick self-contained lookup, or route substantial work to High.
5. Retrieve current evidence from the selected project and explain the result through Voice.
6. If task delegation is connected, offer “Ask the existing project task for a brief status update,” or “Skip the delegation test.”
7. For the selected delegation test, have Voice send the request to High. High checks the project task and returns the actual reply to Voice.

Record Remote access, Live Voice, and delegated execution as separate observations, with dates and evidence. Record the Voice and High role identifiers, hosts, requested settings, and verified settings. A successful voice conversation does not prove that project delegation works. If no delegation route is connected yet, record that test as deferred.

If Live Voice is unavailable, verify Remote with a typed or dictated request and record Voice as deferred. Show the user how to open the known Voice task next time. Keep completed core setup intact.
