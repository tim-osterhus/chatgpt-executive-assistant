# Use your assistant

Open the **Executive Assistant** project and continue in an existing task. Use the model settings you chose. Type or dictate requests in that task; phone Remote and Live Voice are optional interfaces described in [the phone guide](remote-and-voice.md).

## Useful starting requests

- “What needs my attention today? Check the projects I connected.”
- “Connect my website project. It lives in this folder.”
- “Find the latest decision about this project and show me its source.”
- “Ask the existing project task to handle this change, then check what it completed.”
- “Remember that I prefer short answers and want drafts before sending messages.”
- “Continue setup.”
- “Help me connect my phone.”

When an answer is unclear, describe the correction in normal language. The assistant should update the relevant private notes.

## Optional outbound calls

When the [outbound-calling add-on](../addons/outbound-calls/README.md) is installed, you can ask the assistant to call someone or ask it to prepare a call using current project context. Review the proposed recipient, briefing, and purpose before a user-initiated call.

You can also explicitly choose a specific situation and source for a notification call. This is a narrow, user-defined workflow; it does not mean the assistant is continuously monitoring your projects. The assistant does not make its own judgment about what counts as urgent or create an automatic schedule.

The coordinator gathers current information and prepares the call briefing before starting. The voice agent uses the provided briefing during the call and cannot fetch current data or take project actions while speaking. Afterward, the coordinator reviews the saved receipt with you. Treat only confirmed decisions and follow-up as outcomes. If a request's status is uncertain, have the assistant inspect its saved result; do not ask it to redial.

Calls work without Context Mill. Its design is deferred at [addons/context-mill/README.md](../addons/context-mill/README.md).

## Projects stay where they are

This folder holds your preferences and a small map of your connected work. Your existing project folders, knowledge base, and app accounts keep their original roles.

The assistant checks a source when you request current status. Notes in `local/` help a fresh conversation resume without making a second copy of project history.

## Continue in a fresh conversation

Open a new conversation in the same local project and say:

> Read the assistant index and resume where we left off. Check unfinished assignments before sending new work.

The notes in `local/` supply context that survives individual conversations. Check any unfinished call or assignment by its exact request or submission identifier before repeating an action.

## Update the template later

Ask the assistant to review a newer template version before applying changes. Keep your existing `local/` folder and project links. The assistant should compare reusable instructions and preserve your personalized records.
