import os
import re  # Added for stripping markdown
from concurrent.futures import ThreadPoolExecutor
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from openai import OpenAI
from pypdf import PdfReader
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

# Initialize Client
client = OpenAI(
    api_key=os.getenv("PERPLEXITY_API_KEY"),
    base_url="[https://api.perplexity.ai](https://api.perplexity.ai)"
)

# Helper: Define where files get saved
UPLOAD_DIR = os.path.join(settings.BASE_DIR, 'uploads')
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)


# --- HELPERS FOR MAP-REDUCE ---

def clean_ai_response(text):
    """
    Removes Markdown code blocks (```html ... ```) and conversational filler
    to ensure only the raw string remains.
    """
    # Remove opening ```html or ```
    text = re.sub(r'^```(html)?\s*', '', text, flags=re.IGNORECASE)
    # Remove closing ```
    text = re.sub(r'\s*```$', '', text)
    # Remove common chatty prefixes if they appear at the very start
    text = re.sub(r'^(Here is|Sure|Certainly|I have generated).*?:\n', '', text, flags=re.IGNORECASE | re.DOTALL)
    return text.strip()

def split_text(text, chunk_size=3000, overlap=200):
    """Splits long text into overlapping chunks."""
    chunks = []
    start = 0
    text_len = len(text)
    
    while start < text_len:
        end = start + chunk_size
        if end < text_len:
            # Look back to find a clean sentence break
            break_point = -1
            for i in range(end, max(start, end - 500), -1):
                if text[i] in ['.', '\n']:
                    break_point = i + 1
                    break
            
            if break_point != -1:
                end = break_point
        
        chunks.append(text[start:end])
        start = end - overlap 
        
    return chunks

def summarize_chunk(chunk_text):
    """
    MAP STEP: Extract detailed notes.
    CHANGED: Moved from 'summarize concisely' to 'detailed extraction' 
    to prevent data loss before the final step.
    """
    try:
        completion = client.chat.completions.create(
            model="sonar", 
            messages=[
                {"role": "system", "content": "You are a data extractor. Extract all technical definitions, specific numbers, code snippets, and key arguments from the text. Do not summarize; maintain detail."},
                {"role": "user", "content": chunk_text}
            ]
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"Error processing chunk: {e}")
        return ""

def generate_final_summary(combined_summaries):
    """
    REDUCE STEP: Create the detailed HTML document.
    CHANGED: stricter system prompt to ban conversational filler.
    """
    try:
        completion = client.chat.completions.create(
            model="sonar-pro", 
            messages=[
                {"role": "system", "content": """
                    You are a Documentation Engine. 
                    1. Output ONLY raw HTML code. 
                    2. STRICTLY FORBIDDEN: Do not use Markdown code blocks (```). 
                    3. STRICTLY FORBIDDEN: Do not add conversational text like "Here is the HTML".
                    4. Content must be comprehensive, detailed, and professional.
                    5. Use Inline CSS for a professional 'ReadTheDocs' style (fonts: sans-serif, clean borders).
                """},
                {"role": "user", "content": f"""
                Source Data:
                {combined_summaries}
                
                ---
                
                **Task:**
                Convert the source data into a full technical documentation page.
                
                **Structure Requirements:**
                1. **Title:** Use <h1 style="color: #2c3e50; text-align:center;">
                2. **Sections:** Group content logically. Use <h2 style="border-bottom: 2px solid #eaecef; padding-bottom: 0.3em;">.
                3. **Details:** Do not use short bullet points. Use full sentences and detailed explanations.
                4. **Callouts:** Wrap warnings or key notes in <div style="background-color: #f8f9fa; border-left: 4px solid #007bff; padding: 15px; margin: 15px 0;">.
                
                **REQUIRED FOOTER SECTIONS:**
                
                5. **Deep Dive (Next Steps):**
                   - List 3 advanced sub-topics for mastery.
                
                6. **External References:**
                   - Find 3-5 relevant documentation links based on the topics.
                   - Format: <div style="border:1px solid #ddd; padding:10px; border-radius:5px; margin-top:10px;">
                   - Link Format: <a href="URL" target="_blank" style="color: #0366d6; font-weight:bold;">Topic Name</a>
                """}
            ]
        )
        
        # Clean the response to ensure no chatty markdown remains
        raw_content = completion.choices[0].message.content
        clean_html = clean_ai_response(raw_content)
        return clean_html

    except Exception as e:
        raise e

# --- END HELPERS ---


class UploadFileView(APIView):
    """Step 1: Upload the file and get the filename"""
    parser_classes = [MultiPartParser, FormParser]

    @swagger_auto_schema(
        operation_description="Upload a PDF file",
        manual_parameters=[
            openapi.Parameter(
                name='file',
                in_=openapi.IN_FORM,
                type=openapi.TYPE_FILE,
                required=True,
                description='PDF file to upload'
            )
        ],
        responses={200: openapi.Response('File uploaded successfully')}
    )
    def post(self, request):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file provided'}, status=400)

        file_path = os.path.join(UPLOAD_DIR, file_obj.name)
        with open(file_path, 'wb+') as destination:
            for chunk in file_obj.chunks():
                destination.write(chunk)

        return Response({
            'message': 'File uploaded successfully',
            'filename': file_obj.name,
            'path': file_path
        })


class AnalyzeFileView(APIView):
    """Step 2: Send filename to analyze (Handles Long PDFs)"""
    @swagger_auto_schema(
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={'filename': openapi.Schema(type=openapi.TYPE_STRING)},
            required=['filename']
        )
    )
    def post(self, request):
        filename = request.data.get('filename')
        if not filename:
            return Response({'error': 'Please provide a "filename"'}, status=400)

        file_path = os.path.join(UPLOAD_DIR, filename)
        if not os.path.exists(file_path):
            return Response({"error": f"File '{filename}' not found"}, status=404)

        # 1. Extract Text
        try:
            reader = PdfReader(file_path)
            full_text = ""
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"
        except Exception as e:
            return Response({"error": f"PDF Read Error: {str(e)}"}, status=500)

        # 2. Check Length & Decide Strategy
        try:
            if len(full_text) < 3000:
                # Direct processing for short docs
                final_html = generate_final_summary(full_text)
            else:
                # Map-Reduce for long docs
                chunks = split_text(full_text, chunk_size=3000, overlap=200)
                
                # Map Phase (Parallel)
                with ThreadPoolExecutor(max_workers=5) as executor:
                    mini_summaries = list(executor.map(summarize_chunk, chunks))
                
                combined_notes = "\n\n".join(filter(None, mini_summaries))
                
                # Reduce Phase
                final_html = generate_final_summary(combined_notes)
            
            return Response({"analysis": final_html})

        except Exception as e:
            return Response({"error": f"Processing Error: {str(e)}"}, status=500)


class VoiceChatView(APIView):
    """Backend endpoint for voice mode."""
    @swagger_auto_schema(
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'messages': openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Items(type=openapi.TYPE_OBJECT)
                )
            },
            required=['messages']
        )
    )
    def post(self, request):
        messages = request.data.get('messages')
        if not messages:
            return Response({'error': 'Please provide "messages" array'}, status=400)
        
        # Enforce non-chatty system instruction if not present
        system_instruction = {
            "role": "system", 
            "content": "Provide direct, comprehensive answers. Do not use conversational fillers like 'I can help with that'. Go straight to the information."
        }
        
        # Insert system prompt at the start if it doesn't exist
        if messages[0].get('role') != 'system':
            messages.insert(0, system_instruction)

        try:
            completion = client.chat.completions.create(
                model="sonar-pro", 
                messages=messages
            )
            msg = completion.choices[0].message
            return Response({
                "role": msg.role,
                "content": msg.content
            })
        except Exception as e:
            return Response({"error": f"API Error: {str(e)}"}, status=500)