import os
from rest_framework.views import APIView
from rest_framework.response import Response
from openai import OpenAI
from django.conf import settings
from pypdf import PdfReader  # Import the library

client = OpenAI(
    api_key=os.getenv("PERPLEXITY_API_KEY"),
    base_url="https://api.perplexity.ai"
)

class SimpleAnalyzeView(APIView):
    def post(self, request):
        # 1. Locate the file
        file_path = os.path.join(settings.BASE_DIR, 'feature_ds.pdf')

        if not os.path.exists(file_path):
            return Response({"error": f"File not found at {file_path}"}, status=404)

        # 2. Extract Text from PDF
        try:
            reader = PdfReader(file_path)
            pdf_text = ""
            # Loop through pages and grab text
            for page in reader.pages:
                pdf_text += page.extract_text() + "\n"

            # Quick check if PDF was empty or unreadable
            if not pdf_text.strip():
                return Response({"error": "Could not extract text from PDF. It might be empty or scanned images."}, status=400)

        except Exception as e:
            return Response({"error": f"PDF Reading Error: {str(e)}"}, status=500)

        # 3. Send Text to Perplexity
        # Note: We just send the text string now, which is 100% supported.
        try:
            completion = client.chat.completions.create(
                model="sonar-pro",
                messages=[
                    {
                        "role": "system",
                        "content": "Give me a detailed notes on the topics of this pdf with real world examples.And recommend topics to look into with few reference links , give me the document in html format"
                    },
                    {
                        "role": "user",
                        "content": pdf_text
                    }
                ]
            )
            print(completion)
            return Response({"analysis": completion.choices[0].message.content})

        except Exception as e:
            return Response({"error": f"API Error: {str(e)}"}, status=500)