from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Story, Scene, Media

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'bio', 'profile_picture')
        read_only_fields = ('id',)

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
        return user

class MediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Media
        fields = ('id', 'media_type', 'url', 'description', 'created_at')
        read_only_fields = ('id', 'created_at')

class SceneSerializer(serializers.ModelSerializer):
    media = MediaSerializer(many=True, read_only=True)

    class Meta:
        model = Scene
        fields = (
            'id', 'title', 'content', 'order', 'scene_description',
            'created_at', 'updated_at', 'media'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

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