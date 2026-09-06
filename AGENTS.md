tech stack for ALL microservices:

- Python (Flask)
- HTMX
- Alpine.JS
- Jinja Templates
- Postgresql (SQLITE is okay for dev)


Templates:
https://franken-ui.dev/docs/2.1/

AI (all services): local Ollama only — no third-party inference. Every feature
builds a JSON grounding of the facts the model may use, pins a response schema,
runs at low temperature, and refuses rather than guesses. The two chats wrap the
call in a Plan → Act → Observe → Adapt loop. See docs/ai/.
