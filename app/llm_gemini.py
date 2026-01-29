import asyncio
import google.generativeai as genai
from app.config import settings

# Configure the API key once at module initialization
genai.configure(api_key=settings.gemini_api_key)

async def gemini_generate(prompt: str) -> str:
    """
    Generate content using Google Gemini API.
    
    Args:
        prompt: The input prompt for content generation
        
    Returns:
        Generated text content from Gemini
        
    Raises:
        Exception: If generation fails or times out
    """
    # Create the model
    model = genai.GenerativeModel(settings.gemini_model)
    
    # Generate content in async context
    # The SDK doesn't have native async support, so we run it in executor
    loop = asyncio.get_running_loop()
    
    # Note: The timeout is handled at the caller level (pipeline.py, agentic_flow.py)
    # using asyncio.wait_for(), which wraps this entire function call
    response = await loop.run_in_executor(
        None,
        lambda: model.generate_content(prompt)
    )
    
    # Extract text from response with error handling
    if not response or not hasattr(response, 'text'):
        raise Exception("Gemini API returned invalid or empty response")
    
    if not response.text:
        raise Exception("Gemini API returned empty text content")
    
    return response.text
