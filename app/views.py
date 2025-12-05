import os
import base64
from concurrent.futures import ThreadPoolExecutor  # <--- NEW: For parallel processing
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
    base_url="https://api.perplexity.ai"
)

# Helper: Define where files get saved
UPLOAD_DIR = os.path.join(settings.BASE_DIR, 'uploads')
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)


# --- NEW HELPER FUNCTIONS FOR MAP-REDUCE ---

def split_text(text, chunk_size=3000, overlap=200):
    """Splits long text into overlapping chunks."""
    chunks = []
    start = 0
    text_len = len(text)
    
    while start < text_len:
        end = start + chunk_size
        if end < text_len:
            # Try to find the last period or newline to break cleanly
            # Look back from 'end' up to 500 chars to find a sentence break
            break_point = -1
            for i in range(end, max(start, end - 500), -1):
                if text[i] in ['.', '\n']:
                    break_point = i + 1
                    break
            
            if break_point != -1:
                end = break_point
        
        chunks.append(text[start:end])
        start = end - overlap # Overlap to maintain context
        
    return chunks

def summarize_chunk(chunk_text):
    """MAP STEP: Summarize a specific chunk of text."""
    try:
        completion = client.chat.completions.create(
            model="sonar", 
            messages=[
                {"role": "system", "content": "You are a helpful study assistant. Summarize the following text, capturing key topics and definitions concisely."},
                {"role": "user", "content": chunk_text}
            ]
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"Error summarizing chunk: {e}")
        return ""

def generate_final_summary(combined_summaries):
    """REDUCE STEP: Create the final detailed HTML document from the chunk summaries."""
    try:
        completion = client.chat.completions.create(
            model="sonar-pro", 
            messages=[
                # UPDATED SYSTEM PROMPT: Enforces strict HTML output
                {"role": "system", "content": "You are a backend API that generates HTML. Output ONLY valid HTML code. Do not encompass it in markdown code blocks (```). Do not output any conversational text, introductions, or explanations. Start your response immediately with <h1>."},
                {"role": "user", "content": f"""
                Here are the collected notes from the document:
                {combined_summaries}
                
                Task:
                1. Generate a comprehensive study guide based *only* on these notes.
                2. Highlight important topics using <strong> or <em> tags.
                3. Structure the document clearly with <h2>, <h3>, and <ul> tags.
                4. Real-world examples are encouraged if relevant.
                5. STRICT FORMATTING: Your entire response must be raw HTML. Do not say "Here is the document". Just output the HTML.
                """}
            ]
        )
        return completion.choices[0].message.content
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
        # If text is short (< 3000 chars), just do standard processing
        if len(full_text) < 3000:
            try:
                final_html = generate_final_summary(full_text)
                return Response({"analysis": final_html})
            except Exception as e:
                return Response({"error": f"API Error: {str(e)}"}, status=500)

        # 3. Map-Reduce Strategy for Long Texts
        try:
            # A. Split into chunks
            chunks = split_text(full_text, chunk_size=3000, overlap=200)
            
            # B. Map Phase (Parallel Summarization)
            # Use ThreadPoolExecutor to make multiple API calls at once
            mini_summaries = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                results = executor.map(summarize_chunk, chunks)
                mini_summaries = list(results)
            
            # Combine mini summaries into one string
            combined_notes = "\n\n".join(filter(None, mini_summaries))
            
            # C. Reduce Phase (Final Generation)
            final_html = generate_final_summary(combined_notes)
            
            return Response({"analysis": final_html})

        except Exception as e:
            return Response({"error": f"Processing Error: {str(e)}"}, status=500)


class VoiceChatView(APIView):
    """
    Backend endpoint for voice mode.
    Expects JSON: { "messages": [ { "role": "user", "content": "..." }, ... ] }
    """
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