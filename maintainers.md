# Template maintenance and pilot

## Scope

The core release is a Markdown workspace for Codex. A user opens the folder, starts guided setup, connects one useful source, and completes a first task. Core use requires no calling service, background process, Context Mill, or model change.

Outbound calls are a separate, optional local skill and CLI add-on in `addons/outbound-calls/`. Keep its prerequisites, installation steps, tested-platform evidence, and troubleshooting in that add-on's documentation. The deferred Context Mill design is not a running integration.

Keep public instructions generic. Keep all user-specific state under `local/`, which is excluded from Git. Git ignore rules do not sanitize a manually assembled ZIP. Release only intended template files; exclude personal state, credentials, receipts, and local media.

## Sources and freshness

Recheck product labels, availability, permissions, and UI instructions against official documentation before publishing and whenever the desktop or mobile onboarding flow changes. Voice and Remote pages were reviewed on 2026-11-05. Recheck the other reference pages for the selected installation flow:

- [Installation and mode selection](https://learn.chatgpt.com/docs/quickstart).
- [Projects and primary folders](https://learn.chatgpt.com/docs/projects).
- [Windows installation](https://learn.chatgpt.com/docs/windows/windows-app).
- [Dictation](https://learn.chatgpt.com/docs/prompting#use-voice-dictation).
- [Voice](https://learn.chatgpt.com/docs/features/voice).
- [Remote connections](https://learn.chatgpt.com/docs/remote-connections).
- [Computer Use](https://learn.chatgpt.com/docs/computer-use).

Official documentation currently describes Voice in Codex tasks using the selected task model, and mobile access through a connected desktop host. Confirm availability for the user's plan, account, workspace, and rollout before walking them through setup. Recheck links and current product terminology at release time.

## Beginner pilot

Status: pending. Run the first pilot with a nontechnical user starting from the GitHub README. Do not preconfigure their installation beyond what the guide describes.

Record each point where they hesitate, take a wrong branch, or need spoken help. Keep personal observations outside the published template.

The pilot succeeds when the user can:

1. Find the new-user guide from the README.
2. Download and extract the correct folder without using Git or a terminal.
3. Install the app, sign in, and open the folder as a local project.
4. Start guided setup with the supplied message.
5. Answer onboarding questions using suggested choices or their own words.
6. Connect one selected source without a full-computer inventory.
7. Receive one useful, verified result before connecting more sources.
8. Stop and resume setup without repeating finished work.
9. Return to the assistant later and use the saved context.
10. Understand that phone voice and outbound calling are optional and independent.

Check the exact project-creation controls on the pilot's OS. Documentation review does not replace this UI walkthrough. Test each documented desktop OS separately before claiming both routes passed.

## Agent walkthrough checks

- A fresh folder starts onboarding when asked and creates personal files only under `local/`.
- A request to edit or review the template does not launch personal onboarding.
- A beginner receives one useful, verified result immediately after the first connection.
- A power user can connect selected projects in a batch or skip the demonstration.
- Skipped optional personal fields do not block setup.
- A failed connection remains blocked or unverified.
- Paused setup resumes from its recorded step.
- Completed core setup with deferred phone or calling setup starts ordinary work.
- The current task and saved user model choices remain intact; no Voice/High model split is required.
- Existing project tasks keep their ownership. An uncertain dispatch is inspected before retrying.
- Optional Live Voice and outbound calling are described as separate workflows.
- Calling setup is offered after the first useful task and tracked independently from core setup and Remote.
- A call briefing is prepared before the voice agent starts; the voice agent has no live project retrieval or action route.
- The exact saved call receipt is reviewed before reporting decisions or follow-up.
- No blanket monitoring, arbitrary urgency judgment, automatic schedule, or Context Mill dependency is claimed.
- A tool that is unavailable receives an honest fallback, not a fabricated integration.

## Before release

Check relative links from GitHub-rendered Markdown and from the extracted bundle. Check external download links and official UI labels. Review public files for private paths, account details, task identifiers, and credentials. Confirm that `local/` is ignored. Keep untested flows labeled accurately and review the add-on's tested-platform evidence before describing its support.

Retain `SETUP.md` in later versions. Core setup completion and each optional integration status belong in private progress notes.

## Calling implementation checks on November 5 2026

The local candidate passed a fresh add-on dependency install, 20 synthetic tests, shell syntax checks, relative-link checks, and a scan excluding private credentials and generated state from source files. Its downloaded LiveKit 1.13.6 binary passed a synthetic local audio loopback check without a phone call or account login. Both binary archives passed pinned checksum verification.

Independent review found and rechecked fixes for unexpected voice-process EOF and incidental farewell detection. Personal settings include a configurable 45-minute safety cap and optional spoken disclosure. The earlier live personal call and its limits are documented in the add-on overview. These checks do not establish a new adopter's account entitlement, a full-duration call, a beginner walkthrough, or a Dot-originated request in every installation.
