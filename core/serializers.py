from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Story, Scene, Media, Revision, Credits, CreditTransaction, Order, Payment, Job

User = get_user_model()

class CreditSerializer(serializers.ModelSerializer):
    class Meta:
        model = Credits
        fields = ('credits_remaining', 'updated_at')

class UserSerializer(serializers.ModelSerializer):
    credits = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'bio', 'profile_picture', 'credits', 'referral_code', 'language')
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
        fields = ('username', 'email', 'password', 'referral_code', 'language')

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            referral_code=validated_data.get('referral_code')  # Add referral code during user creation
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
            'updated_at', 'is_public', 'word_count', 'scenes', 'is_default', 'language'
        )
        read_only_fields = ('id', 'author', 'created_at', 'updated_at', 'word_count', 'is_default', 'language')

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
            'created_at', 'created_by', 'is_current',
            'metadata'
        ]
        read_only_fields = ['created_at', 'is_current'] 

class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ['id', 'user', 'amount', 'status', 'created_at', 'updated_at', 'order_id', 'metadata']
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

class JobSerializer(serializers.ModelSerializer):
    """Serializer for the Job model."""
    class Meta:
        model = Job
        fields = [
            'id', 'message_id', 'job_type', 'status',
            'user', 'story', 'scene', 'request_data', 'response_data',
            'error_message', 'created_at', 'started_at', 'completed_at',
            'updated_at', 'retry_count', 'max_retries', 'next_retry_at'
        ]
        read_only_fields = [
            'id', 'message_id', 'created_at', 'started_at',
            'completed_at', 'updated_at', 'retry_count', 'next_retry_at'
        ]

class JobCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new jobs."""
    class Meta:
        model = Job
        fields = [
            'job_type', 'user', 'story', 'scene', 'request_data'
        ]