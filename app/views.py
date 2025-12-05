import os
import base64
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
    base_url="https://api.perplexity.ai"
)

# Helper: Define where files get saved
UPLOAD_DIR = os.path.join(settings.BASE_DIR, 'uploads')
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)


# --- HELPERS FOR MAP-REDUCE ---

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
    """
    REDUCE STEP: Create the detailed HTML document.
    UPDATED: Now requests distinct sections for Related Topics with hyperlinks and inline CSS.
    """
    try:
        completion = client.chat.completions.create(
            model="sonar-pro", 
            messages=[
                {"role": "system", "content": """
                    You are an intelligent backend API that generates rich HTML content. 
                    1. Output ONLY valid HTML code. 
                    2. Do not use Markdown code blocks (```). 
                    3. Do not include conversational filler ("Here is the HTML").
                    4. Use Inline CSS to style the elements beautifully (modern, clean design).
                """},
                {"role": "user", "content": f"""
                Here are the collected notes from a uploaded document:
                {combined_summaries}
                
                ---
                
                **Task:**
                Generate a comprehensive, structured Study Guide HTML document based on these notes.
                
                **Formatting Requirements:**
                1. **Main Content:** Use `<h2>` for major sections and `<ul>`/`<li>` for details. Use `<strong>` for key terms.
                2. **Style:** Apply inline CSS. e.g., `<h2 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px;">`.
                3. **Key Concepts:** Wrap vital definitions in a styled `<div>` box (e.g., light gray background, left border).
                
                **REQUIRED NEW SECTIONS (At the bottom):**
                
                4. **Recommended Further Study:** - Suggest 3 specific sub-topics the user should learn next to master this subject.
                   - Present these as a list.
                
                5. **Related Resources & Links:**
                   - Identify 3-5 external concepts mentioned or related to the text.
                   - Search your knowledge base to find relevant, high-quality external links (Documentation, Wikipedia, or Educational resources).
                   - **CRITICAL:** Output actual HTML hyperlinks: `<a href="URL" target="_blank" style="color: #2980b9; text-decoration: none; font-weight: bold;">Link Title</a>`.
                   - Format this section using a "Card" look (div with border, padding, and slight shadow).
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