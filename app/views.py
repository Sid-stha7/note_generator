import os
import base64
from django.conf import settings
from rest_framework.views import APIView  # <--- THIS WAS MISSING
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
    """Step 2: Send filename to analyze"""
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

        try:
            reader = PdfReader(file_path)
            pdf_text = ""
            for page in reader.pages:
                pdf_text += page.extract_text() + "\n"
        except Exception as e:
            return Response({"error": f"PDF Error: {str(e)}"}, status=500)

        try:
            completion = client.chat.completions.create(
                model="sonar-pro",
                messages=[
                    {"role": "system", "content": "Analyze this text."},
                    {"role": "user", "content": pdf_text}
                ]
            )
            return Response({"analysis": completion.choices[0].message.content})
        except Exception as e:
            return Response({"error": f"API Error: {str(e)}"}, status=500)


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
                model="sonar-pro",  # or another supported chat model[web:8]
                messages=messages
            )
            msg = completion.choices[0].message
            return Response({
                "role": msg.role,
                "content": msg.content
            })
        except Exception as e:
            return Response({"error": f"API Error: {str(e)}"}, status=500)