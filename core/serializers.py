from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Story, Scene, Media, Revision, Credits, CreditTransaction, Order, Payment

User = get_user_model()

class CreditSerializer(serializers.ModelSerializer):
    class Meta:
        model = Credits
        fields = ('credits_remaining', 'updated_at')

class UserSerializer(serializers.ModelSerializer):
    credits = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'bio', 'profile_picture', 'credits')
        read_only_fields = ('id',)

    def get_credits(self, obj):
        credit = Credits.objects.filter(user=obj, is_active=True).first()
        return CreditSerializer(credit).data if credit else {'credits_remaining': 0, 'updated_at': None}

class UserRegistrationSerializer(serializers.ModelSerializer):
    """
    Serializer for user registration.
    """
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'password')

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password']
        )
        # Create initial credits for the user
        Credits.objects.create(
            user=user,
            credits_remaining=300,  # Default credits
            is_active=True
        )
        return user

class MediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Media
        fields = ('id', 'media_type', 'url', 'description', 'created_at', 'is_active')
        read_only_fields = ('id', 'created_at')

class SceneSerializer(serializers.ModelSerializer):
    media = serializers.SerializerMethodField()

    class Meta:
        model = Scene
        fields = (
            'id', 'title', 'content', 'order', 'scene_description',
            'created_at', 'updated_at', 'media'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def get_media(self, obj):
        active_media = obj.media.filter(is_active=True)
        return MediaSerializer(active_media, many=True).data

class StorySerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    scenes = SceneSerializer(many=True, read_only=True)

    class Meta:
        model = Story
        fields = (
            'id', 'title', 'content', 'author', 'created_at',
            'updated_at', 'is_public', 'word_count', 'scenes'
        )
        read_only_fields = ('id', 'author', 'created_at', 'updated_at', 'word_count')

class StoryCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Story
        fields = ('id', 'title', 'content', 'is_public')

    def create(self, validated_data):
        print(self.context)
        # Get the authenticated user from the request context and set as author
        validated_data['author'] = self.context['request'].user
        # Call parent class's create() method with the validated data including author
        return super().create(validated_data) 
class RevisionSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    story = serializers.StringRelatedField()

    class Meta:
        model = Revision
        fields = [
            'id', 'story', 'format', 'sub_format', 'url',
            'created_at', 'created_by', 'version', 'is_current',
            'metadata'
        ]
        read_only_fields = ['created_at', 'version', 'is_current'] 

class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ['id', 'user', 'amount', 'status', 'created_at', 'updated_at', 'order_id']
        read_only_fields = ['id', 'created_at', 'updated_at']

class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ['id', 'order', 'payment_id', 'payment_status', 'payment_signature', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

class CreditTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditTransaction
        fields = ['id', 'user', 'credits_used', 'transaction_type', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']