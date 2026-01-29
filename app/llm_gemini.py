import asyncio
import google.generativeai as genai
from app.config import settings

async def gemini_generate(prompt: str) -> str:
    """
    Generate content using Google Gemini API.
    
    Args:
        prompt: The input prompt for content generation
        
    Returns:
        Generated text content from Gemini
    """
    # Configure the API key
    genai.configure(api_key=settings.gemini_api_key)
    
    # Create the model
    model = genai.GenerativeModel(settings.gemini_model)
    
    # Generate content in async context
    # The SDK doesn't have native async support, so we run it in executor
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: model.generate_content(prompt)
    )
    
    # Extract text from response
    return response.text
