from rest_framework import serializers
from .models  import*



class PDFUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

class ProductSerializer(serializers.ModelSerializer):
    class Meta():
        model = Product
        fields = "__all__"

