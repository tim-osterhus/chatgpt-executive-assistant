# Template maintenance and pilot

## Scope

The first release is a Markdown workspace for the Codex desktop workflow. The user downloads a folder and starts guided setup. No custom application or background service is part of this template.

Keep public instructions generic. Keep all user-specific state in `local/`, which is excluded from Git. Git ignore rules do not sanitize a manually assembled ZIP. Release only tracked template files, excluding personal state, credentials, receipts, and local media.

## Sources and freshness

UI instructions and pricing were checked against official documentation on 2026-09-11. Recheck these before publishing and whenever the desktop onboarding flow changes:

- [Installation and mode selection](https://learn.chatgpt.com/docs/quickstart).
- [Projects and primary folders](https://learn.chatgpt.com/docs/projects).
- [Windows installation](https://learn.chatgpt.com/docs/windows/windows-app).
- [Pricing](https://learn.chatgpt.com/docs/pricing).
- [Dictation](https://learn.chatgpt.com/docs/prompting#use-voice-dictation).
- [Voice](https://learn.chatgpt.com/docs/features/voice).
- [Computer Use](https://learn.chatgpt.com/docs/computer-use).
- [Remote connections](https://learn.chatgpt.com/docs/remote-connections).

Official documentation names the installer product ChatGPT and the agent mode Codex. The Mac installer filename remains `Codex.dmg`. Follow the actual product labels when these change.

## Beginner pilot

Status: pending. Run the first pilot with a nontechnical user starting from the GitHub README. Do not preconfigure their installation beyond what the guide describes.

Record each point where they hesitate, take a wrong branch, or need spoken help. Keep personal observations outside the published template.

The pilot succeeds when the user can:

1. Find the new-user guide from the README.
2. Download and extract the correct folder without using Git or a terminal.
3. Install the app, sign in, and open the folder as a local project.
4. Start guided setup with the supplied message.
5. Answer each onboarding question using suggested choices or their own words.
6. Find dictation with the assistant's help if they want to speak.
7. Connect one selected source without a full-computer inventory.
8. Receive one useful, verified result before connecting more sources.
9. Stop and resume setup without repeating finished work.
10. Return to the assistant later and use the saved context.

Check the exact project-creation controls and microphone position on the pilot's OS. Documentation review does not replace this UI walkthrough. Test the other documented desktop OS separately before claiming both routes passed.

## Agent walkthrough checks

- A fresh folder starts onboarding when asked and creates personal files only under `local/`.
- A request to edit or review the template does not launch personal onboarding.
- A beginner receives short explanations and a first useful task immediately after the first connection.
- A power user can batch selected connections and skip the demonstration.
- Skipped age or other optional bio does not block setup.
- A failed connection remains blocked or unverified.
- Paused setup resumes from its recorded step.
- Completed core setup with deferred phone access starts ordinary work.
- Existing project tasks keep their ownership. An uncertain dispatch is inspected before retrying.
- A tool that is unavailable receives an honest fallback, not a fabricated integration.

## Before release

Check relative links from GitHub-rendered Markdown and from the extracted bundle. Check external download links and official UI labels. Review all public files for private paths, account details, task identifiers, and credentials.

Keep templates free of actual personal records. Confirm that `local/` is ignored. Validate the beginner guide through the pilot, fix observed friction, and record tested platforms and dates. Keep untested flows labeled accurately.

Retain `SETUP.md` in later versions. Setup completion belongs in each user's personal progress file.

## Documentation preflight: 2026-09-11

- All 21 relative Markdown links resolve in the template folder.
- Seven sample personal-state, credential-file, and operating-system paths match the Git ignore rules.
- The public-text scan found no private machine paths, account labels, or task identifiers from the source workspace.
- Thirteen external URLs returned HTTP 200, including both installers. Automated requests to ChatGPT sign-in and upgrade returned HTTP 403. Those destinations match official documentation.
- The writing audit was reviewed. The conversational ChatGPT helper sentence is intentional. List and table paragraph warnings do not represent prose paragraphs.
- An independent agent review traced beginner, power-user, interrupted, completed, and unavailable-tool cases through the instructions. It did not execute those flows.

These are documentation checks. Installation, live integration, and the beginner pilot remain untested.
