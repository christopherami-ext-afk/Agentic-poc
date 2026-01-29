import asyncio
from copilot import CopilotClient

async def copilot_generate(prompt: str) -> str:
    """
    Similar to your ollama_generate(), but uses GitHub Copilot SDK (Python).

    Requires:
      - Copilot CLI installed + authenticated
      - github-copilot-sdk Python package
    """
    client = CopilotClient()  # can also pass {"cli_path": "..."} if needed
    await client.start()

    # Create a chat session (pick a model your Copilot org/plan supports)
    session = await client.create_session({"model": "gpt-5"})  # example from SDK docs

    done = asyncio.Event()
    chunks: list[str] = []

    def on_event(event):
        # The SDK streams events; collect assistant messages until the session goes idle.
        if event.type.value == "assistant.message":
            chunks.append(event.data.content)
        elif event.type.value == "session.idle":
            done.set()

    session.on(on_event)

    await session.send({"prompt": prompt})
    await done.wait()

    await session.destroy()
    await client.stop()

    return "".join(chunks).strip()
